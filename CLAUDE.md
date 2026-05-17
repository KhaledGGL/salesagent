# Sales Call Analyzer / Marketing Analyzer — Project Guide

> **Companion docs:**
> - [`STATUS.md`](./STATUS.md) — what's done, what's pending, how to resume
> - [`INSTALL.md`](./INSTALL.md) — step-by-step deployment guide
> - [`MARKETING_ANALYZER_PLAN.md`](./MARKETING_ANALYZER_PLAN.md) — milestone 2 design
> - [`PHASE_0_REFACTOR_PLAN.md`](./PHASE_0_REFACTOR_PLAN.md) — modular monorepo refactor (live)
>
> **Read STATUS first** if you're picking up work in progress.
> **Read INSTALL** if you're deploying this system for the first time.
> This file covers stable conventions only.

## Products

This monorepo houses two independently-sellable products that share a
common infrastructure layer:

- **Sales Call Analyzer** (live in production): GHL webhook → Claude
  scoring → Slack scorecards + weekly reports. Stack: `core/` + `sales/`.
- **Marketing Analyzer** (Phase 0 skeleton; Phase 1 in design partner
  build with Calivus): ad-platform ingest → funnel pipeline → closed-loop
  with sales. Stack: `core/` + `marketing/`.

Both products deploy per-client on dedicated VPSes (transferable license
model). See `MARKETING_ANALYZER_PLAN.md` for the architectural rationale.

## Stack
- **API:** FastAPI (uvicorn)
- **Task queue:** Celery with Redis broker
- **Database:** Supabase (Postgres) via `supabase-py` (≥2.28 for new sb_secret key format)
- **AI:** Anthropic Claude API (Sonnet 4.6 for scoring)
- **Notifications:** Slack Bot
- **Source CRM:** GoHighLevel by default, but the webhook contract is
  CRM-agnostic — see INSTALL.md Appendix A for adapting to other CRMs
- **Reverse proxy:** Caddy (in `infra/caddy/`)
- **Image registry:** GHCR — `ghcr.io/khaledggl/gogrowlabs-{sales,marketing}`
- **Fleet updates:** Watchtower on each VPS auto-pulls `:stable` tag

## Project Structure

```
core/                          # Shared infrastructure (both products)
  config.py                    # pydantic-settings, all env vars
  db.py                        # Supabase client singleton
  logging.py                   # Structured JSON / plaintext switch
  observability.py             # Sentry init
  redis.py                     # Redis client singleton

sales/                         # Sales Call Analyzer product
  Dockerfile                   # Image: ghcr.io/khaledggl/gogrowlabs-sales
  schemas.py                   # Pydantic models + enums (mirror SQL enums)
  migrations/                  # 001-008 SQL migrations
  app/
    main.py                    # FastAPI entrypoint, /health, /health/ready
    cli.py                     # Replay CLI: run-weekly-report, replay --call-id …
    webhooks/ghl.py            # POST /webhooks/ghl/transcript-ready (sole ingest)
    services/
      claude_client.py         # Anthropic SDK wrapper
      slack_client.py          # Slack Web API + retries
    core/
      prompts.py               # NEPQ/AHM scoring rubric + JSON schema spec
      slack_blocks.py          # Per-call scorecard Block Kit
      report_blocks.py         # Weekly report Block Kit
      coaching_blocks.py       # Coaching lesson Slack blocks
      marketing_blocks.py      # Marketing-intel Slack blocks
    workers/
      celery_app.py            # Celery config + beat schedule
      tasks.py                 # score_call → notify_scorecard, weekly reports
    ui/                        # Server-rendered dashboard (/ui/*)
    templates/                 # Jinja2 templates
  tests/                       # 265 tests, ~2.8s, zero external deps

marketing/                     # Marketing Analyzer (Phase 0 skeleton)
  Dockerfile                   # Image: ghcr.io/khaledggl/gogrowlabs-marketing
  schemas.py                   # Phase 1 will populate
  migrations/                  # Phase 1 will populate
  app/
    main.py                    # /health, /health/ready (skeleton)
    workers/celery_app.py      # Empty celery skeleton
  tests/                       # Empty conftest only

deploy/                        # Bundle compose files (canonical)
  compose.sales-only.yml       # Sales product alone
  compose.marketing-only.yml   # Marketing product alone
  compose.combined.yml         # Both products, shared redis/caddy/flower
  compose.dev.yml              # Hot-reload overlay, layers on any bundle

requirements/
  shared.txt                   # Deps used by both products
  sales.txt                    # `-r shared.txt` + anthropic + slack-sdk
  marketing.txt                # `-r shared.txt` + (Phase 1 will add)
  dev.txt                      # All runtime deps + pytest tooling

docker-compose.yml             # Backward-compat wrapper: `include: deploy/compose.sales-only.yml`
infra/
  caddy/                       # Standalone reverse proxy (multi-agent VPS)
.github/workflows/
  ci.yml                       # pytest + matrix Dockerfile build check
  publish-images.yml           # GHCR push on master commit
```

## Conventions
- HTTP client: `httpx` (never `requests`)
- Settings: always via `from core.config import settings`, never raw `os.getenv`
- DB access: always via `core.db.get_supabase()`, never direct client creation
- Pydantic models for all API boundaries (webhook payloads, Claude output)
- Celery tasks use `bind=True`, `acks_late`, and retry with backoff
- Enums defined once in product `schemas.py`, mirrored in SQL
- supabase-py 2.28+ returns `None` (not `APIResponse(data=None)`) from
  `maybe_single().execute()` when no row matches — always check
  `if row is not None and row.data:` before accessing `.data`
- New product code goes under `sales/app/` or `marketing/app/`; shared
  infrastructure goes under `core/` (only if it's genuinely consumed by
  both products — avoid speculative sharing)

## Running

### Local dev (single product, no proxy)
```bash
# One-time on this host: create the shared `web` network the compose
# files reference (harmless even if you don't run Caddy)
docker network create web

# Default BUNDLE=sales-only
make up                            # production-like (no hot-reload)
make dev                           # dev overlay (hot-reload + APP_ENV=development)
make test                          # 265 tests, ~2.8s

# Override bundle:
make up BUNDLE=marketing-only
make up BUNDLE=combined

# Per-product test runs:
make test-sales
make test-marketing

# After any prompts.py change, restart the worker (Celery caches imports):
docker compose -f deploy/compose.sales-only.yml restart worker beat
```

### Multi-agent VPS (with Caddy)
See `infra/caddy/README.md` for the host setup. After Phase 0 rollout,
client VPSes pull `:stable` images from GHCR via Watchtower — no SSH
needed for routine updates.

### Endpoints (local dev — bound to 127.0.0.1 only)

Sales-only bundle:
- API: http://localhost:8000
- Health: http://localhost:8000/health  +  /health/ready
- Flower: http://localhost:5555
- Redis: localhost:6379

Marketing-only bundle (different ports to coexist with sales):
- API: http://localhost:8001
- Health: http://localhost:8001/health  +  /health/ready
- Flower: http://localhost:5556
- Redis: localhost:6380

Combined bundle:
- Sales API: http://localhost:8000
- Marketing API: http://localhost:8001
- Shared Flower: http://localhost:5555
- Shared Redis: localhost:6379

## Webhook contract (sole sales ingestion path)

`POST /webhooks/ghl/transcript-ready` is the only sales ingest endpoint.

```json
{
  "call_sid": "<unique per call, used for dedup>",
  "call_user_id": "<rep's CRM user ID>",
  "call_user_name": "<rep's display name>",
  "call_transcript": "<the full transcript text, ≥50 chars>",
  "call_status": "completed",
  "contact_id": "<CRM contact ID>",
  "call_duration": 387,
  "contact_name": "optional",
  "contact_email": "optional",
  "contact_phone": "optional",

  "utm_source":   "facebook | google | tiktok | direct | ...",
  "utm_medium":   "cpc | cpm | social | organic | ...",
  "utm_campaign": "campaign name from the ad URL",
  "utm_content":  "creative variant",
  "utm_term":     "keyword (Google search ads)"
}
```

The body parser is tolerant: strict JSON, JSON with unescaped newlines/
quotes inside the transcript value (auto-repaired), form-urlencoded,
and form-urlencoded with a wrapped `payload` field.

`utm_source` is normalized into the `lead_source` enum
(`meta` / `google` / `organic`) for the dashboard. The full UTM set is
preserved on dedicated columns for campaign / creative / keyword analysis.

## Marketing webhook contracts

Phase 1 will add `marketing/app/webhooks/` with endpoints for form
submits, calendar bookings, and generic stage events. Not implemented
yet — see `MARKETING_ANALYZER_PLAN.md` for the planned contract.

## Environment
- Copy `.env.example` to `.env` at the repo root and fill in real values
- `APP_ENV=production` enforces HMAC webhook signatures; `development` bypasses
- Never commit `.env` (it's in `.gitignore`)
- Rotate any credential that's ever been pasted in chat / screenshots / commits
- Bundle compose files reference `.env` at repo root (`../.env` from `deploy/`)
