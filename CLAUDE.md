# Sales Call Analyzer — Project Guide

> **Two companion docs:**
> - [`STATUS.md`](./STATUS.md) — what's done, what's pending, and how to resume work
> - [`INSTALL.md`](./INSTALL.md) — step-by-step deployment guide for any environment
>
> **Read STATUS first** if you're picking up work in progress.
> **Read INSTALL** if you're deploying this system for the first time.
> This file (CLAUDE.md) covers stable conventions only.

## Stack
- **API:** FastAPI (uvicorn)
- **Task queue:** Celery with Redis broker
- **Database:** Supabase (Postgres) via `supabase-py` (≥2.28 for new sb_secret key format)
- **AI:** Anthropic Claude API (Sonnet 4.6 for scoring)
- **Notifications:** Slack Bot
- **Source CRM:** GoHighLevel by default, but the endpoint contract is
  CRM-agnostic — see INSTALL.md Appendix A for adapting to other CRMs

## Project Structure
```
app/
  main.py                  # FastAPI entrypoint, /health and /health/ready
  db.py                    # Supabase client singleton
  webhooks/ghl.py          # Two webhook endpoints:
                           #   /webhooks/ghl/call-completed   (legacy, GHL fetches transcript)
                           #   /webhooks/ghl/transcript-ready (current, transcript inline)
  services/
    ghl_client.py          # GHL Conversations + Contacts API client
    claude_client.py       # Anthropic SDK wrapper, JSON parsing, prompt drift detection
    slack_client.py        # Slack Web API + retries
  core/
    prompts.py             # NEPQ/AHM scoring rubric + explicit JSON schema spec
    slack_blocks.py        # Per-call scorecard Block Kit builder
    report_blocks.py       # Weekly report Block Kit builder
  workers/
    celery_app.py          # Celery config (Redis broker, beat schedule)
    tasks.py               # process_call → score_call → notify_scorecard, generate_weekly_report
  cli.py                   # Replay CLI: run-weekly-report, replay --call-id <uuid>
  observability.py         # Sentry init, structured JSON logging
config.py                  # pydantic-settings, all env vars
schemas.py                 # Pydantic models & enums (mirror SQL enums)
001_initial.sql            # Tables, indexes, triggers, enums
002_views.sql              # 30-day rolling + objection-tracking views
003_weekly_views.sql       # Weekly report views
tests/                     # 124 tests, ~2s runtime, zero external deps
infra/
  caddy/                   # Standalone Caddy reverse proxy for multi-agent
                           # VPS deployments. Path-based routing under
                           # api.<DOMAIN>; salesagent lives at /salesgrader/*.
                           # See infra/caddy/README.md for host setup.
INSTALL.md                 # Deployment guide (read for any first-time setup)
STATUS.md                  # Current state, pending work, resume notes
```

## Conventions
- HTTP client: `httpx` (never `requests`)
- Settings: always via `config.settings`, never raw `os.getenv`
- DB access: always via `app.db.get_supabase()`, never direct client creation
- Pydantic models for all API boundaries (webhook payloads, Claude output)
- Celery tasks use `bind=True`, `acks_late`, and retry with backoff
- Enums defined once in `schemas.py`, mirrored in SQL
- supabase-py 2.28+ returns `None` (not `APIResponse(data=None)`) from
  `maybe_single().execute()` when no row matches — always check
  `if row is not None and row.data:` before accessing `.data`

## Running

### Local dev (single agent, no proxy)
```bash
# One-time on this host: create the shared `web` network the compose
# file references (harmless even if you don't run Caddy)
docker network create web

make up                    # production-like (no hot-reload)
make dev                   # dev overlay (hot-reload + APP_ENV=development)
make test                  # 124 tests, ~2s

# After any prompts.py change, restart the worker (Celery caches imports):
docker compose restart worker beat
```

### Multi-agent VPS (with Caddy)
See `infra/caddy/README.md` for the full host setup. Salesagent's
public URL becomes `https://api.<DOMAIN>/salesgrader/*` once Caddy
is up.

### Endpoints (local dev — bound to 127.0.0.1 only)
- API: http://localhost:8000
- Health: http://localhost:8000/health  +  /health/ready
- Flower (Celery monitoring): http://localhost:5555
- Redis: localhost:6379 (only reachable from the host itself)

## Webhook contract (current)

`POST /webhooks/ghl/transcript-ready` accepts inline-transcript payloads:

```json
{
  "call_sid": "<unique per call, used for dedup>",
  "call_user_id": "<rep's CRM user ID>",
  "call_transcript": "<the full transcript text, ≥50 chars>",
  "call_status": "completed",
  "contact_id": "<CRM contact ID>",
  "call_duration": 387,
  "contact_name": "optional",
  "contact_email": "optional",
  "contact_phone": "optional"
}
```

The body parser is tolerant: it accepts strict JSON, JSON with
unescaped newlines/quotes inside the transcript value (auto-repaired),
form-urlencoded, and form-urlencoded with a wrapped `payload` field.

## Environment
- Copy `.env.example` to `.env` and fill in real values
- `APP_ENV=production` enforces HMAC webhook signatures; `development` bypasses
- Never commit `.env` (it's in `.gitignore`)
- Rotate any credential that's ever been pasted in chat / screenshots / commits
