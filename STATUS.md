# Project Status — Sales Call Analyzer

**Last updated:** 2026-04-06
**Current commit:** `e82bf7a`
**Phase:** v0.1 code-complete, database bootstrapped, pending external services + first live run

---

## What this product does

Ingests sales call recordings from GoHighLevel webhooks, transcribes them,
scores them with Claude (NEPQ/AHM rubric across 5 categories), and posts
per-call scorecards plus a weekly team report to Slack.

## Pipeline

```
GHL webhook
    ↓
process_call        (fetch transcript, enrich from contact)
    ↓
score_call          (Claude Sonnet 4.6 → scorecard → DB)
    ↓
notify_scorecard    (Slack: main message + threaded coaching)

+ Celery beat (Monday 8am configurable):
    ↓
generate_weekly_report  (aggregates views → KPI snapshots → Slack)
```

---

## Build status

### Code — complete ✅

| Step | Area | Status |
|---|---|---|
| 1 | DB schema (`001_initial.sql`) | ✅ Done |
| 2 | Analytical views (`002_views.sql`) | ✅ Done |
| 3 | Pydantic models (`schemas.py`) | ✅ Done |
| 4 | Config + scaffold | ✅ Done |
| 5 | GHL ingest + webhook signature | ✅ Done |
| 6 | Claude scoring + enrichment | ✅ Done |
| 7 | Slack per-call notification | ✅ Done |
| 8 | Weekly report via Celery beat | ✅ Done |
| 9 | Ops polish (Sentry, readiness, CLI) | ✅ Done |

### Infra — complete ✅

- Multi-stage Dockerfile, non-root user, HEALTHCHECK
- `docker-compose.yml` (prod) + `docker-compose.dev.yml` (hot-reload overlay)
- Makefile with `up`, `dev`, `down`, `logs`, `shell`, `test`, `test-fast`, `install-dev`, `clean`
- Structured JSON logging (prod) / plaintext (dev)
- Pinned dependencies in `requirements.txt` + `requirements-dev.txt`
- `.gitignore`, `.dockerignore`
- `CLAUDE.md` project conventions

### Tests — complete ✅

**111 tests, ~1.6s runtime, zero external dependencies.**

| File | Tests | Covers |
|---|---|---|
| `test_webhook_signature.py` | 6 | HMAC-SHA256 verification |
| `test_ghl_client.py` | 17 | Source attribution (Meta/Google/Organic) |
| `test_task_helpers.py` | 14 | Lead temperature, custom fields, enrichment |
| `test_claude_client.py` | 9 | JSON parsing, fence stripping, validation |
| `test_slack_blocks.py` | 29 | Per-call scorecard Block Kit |
| `test_report_blocks.py` | 23 | Weekly report Block Kit |
| `test_healthcheck.py` | 5 | Liveness + readiness endpoints |
| `test_cli.py` | 8 | Replay CLI argparse + dispatch |

### CI/CD — complete ✅

- GitHub Actions workflow at `.github/workflows/ci.yml`
- Runs on every push + PR to `master` / `main`
- Two jobs: `pytest` (~30s cached) + `docker build` (~30s cached)
- Concurrency cancellation on rapid pushes
- `permissions: contents: read` (least privilege)
- Node 24 runtime opt-in for upstream action deprecation

### Database — bootstrapped ✅

All three migrations applied against live Supabase:

- `001_initial.sql` — enums, tables, indexes, triggers
- `002_views.sql` — `v_rep_performance_30d`, `v_cold_warm_comparison`,
  `v_therapist_mode_trend`, `v_weekly_objections`
- `003_weekly_views.sql` — `v_rep_performance_weekly`, `v_weekly_overview`,
  `v_top_objections_weekly`

---

## What's NOT done yet

### External services (Step 10b) — ⏳ pending

You need to create accounts and collect credentials for:

- [ ] **Supabase project** — ✅ created, need to copy `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` into `.env`
- [ ] **GHL Private Integration** — scopes: `conversations.readonly`,
  `conversations/message.readonly`, `contacts.readonly`. Collect API key +
  Location ID. Webhook trigger configured but NOT YET ACTIVATED.
- [ ] **Anthropic API key** — with a $50/month hard spending limit set in Console
- [ ] **Slack app** — bot scopes `chat:write` + `chat:write.public`;
  install to workspace; create `#sales-scorecards` and `#sales-reports`;
  **invite the bot to both channels** (common gotcha)
- [ ] **Sentry** — optional; leave `SENTRY_DSN=` blank to disable cleanly

### `.env` file — ⏳ pending

Copy `.env.example` → `.env` and fill in real values. For local dev:

- `APP_ENV=development`
- `REDIS_URL=redis://redis:6379/0` (leave as-is, docker-compose handles it)
- `SECRET_KEY` and `WEBHOOK_SECRET` can be any random string for dev:
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  ```

### First live run (Step 10c) — ⏳ blocked on `.env`

Once `.env` is populated:

```bash
make dev                              # spins up API + worker + beat + Redis + Flower
curl localhost:8000/health            # → {"status":"ok"}
curl localhost:8000/health/ready      # → supabase:ok redis:ok
docker compose exec worker python -m app.cli run-weekly-report
# → should post "No scored calls this week" to #sales-reports
```

If the weekly report posts successfully against zero data, the full
Slack + Supabase + Celery integration is verified.

### First real call (Step 10d) — ⏳ blocked on 10c

Two options:

- **Safer:** `curl` a synthetic webhook payload at
  `localhost:8000/webhooks/ghl/call-completed`. GHL fetch will fail on
  the fake message ID; you'll see exactly where the pipeline handles that.
- **Bold:** ngrok-tunnel localhost:8000, register the URL in GHL,
  make a real test call, watch real data flow through.

### Deployment (Step 11) — ⏳ blocked on 10

Recommended target: **Fly.io** (multi-process support, managed Redis,
Dockerfile deploys, <$10/month at this scale).

### Admin UI (Step 12) — 🔒 deferred

Deliberately not built. Real managers need to use Slack scorecards for
~1 week before we know what a dashboard should show.

### Runbook / ops docs (Step 13) — 🔒 deferred

Write after you've personally done the first deploy. Your friction
points are exactly what the doc should cover.

---

## How to resume

1. **Read this file** to remember where you left off
2. **Optional: re-read `CLAUDE.md`** for coding conventions
3. **Work through the ⏳ pending checklist above** in order
4. **When ready for Claude Code,** just say "let's pick up where we left off"
   — the memory system and this file together will re-orient the assistant instantly

### Sanity checks you can run anytime

```bash
# Tests still green locally?
make test

# Repo clean?
git status

# Latest commits?
git log --oneline -10
```

---

## Key architectural decisions (reference)

- **Sonnet 4.6 for scoring**, not Opus — structured extraction doesn't need
  deep reasoning; Sonnet is ~5x cheaper with ~95% quality parity
- **Lead enrichment happens in `process_call`**, not `score_call` — scoring
  stays a pure function (transcript in → scorecard out), trivially unit-testable
- **`notify_scorecard` is a separate task**, not inlined — Slack outages
  cannot corrupt a successfully-scored call's status
- **SQL views own "last week" date math**, not Python — timezone + week
  boundary bugs live in one place, not scattered across task code
- **3-call qualification threshold** for top performers / needs coaching —
  prevents single-outlier reps from polluting weekly rankings
- **Redis AOF persistence** in docker-compose — queue survives restarts;
  without this, in-flight scoring jobs are lost on `docker compose restart`
- **Readiness check separate from liveness** — orchestrators can pull
  unready pods from rotation without killing them
- **Replay CLI uses `.delay()` not direct execution** — inherits normal
  Celery retry semantics; operator just enqueues, system does the rest

---

## Files you'll touch most often

| File | When to look here |
|---|---|
| `.env` | Any credential change |
| `app/workers/tasks.py` | Adding/editing pipeline stages |
| `app/core/prompts.py` | Tuning the scoring rubric |
| `app/core/slack_blocks.py` | Changing per-call Slack formatting |
| `app/core/report_blocks.py` | Changing weekly report formatting |
| `CLAUDE.md` | Codifying new conventions |
| `STATUS.md` (this file) | Every meaningful status change |
