# Project Status — Sales Call Analyzer (+ Marketing Analyzer)

**Last updated:** 2026-05-17
**Current phase:** v0.4 — modular monorepo (core/ + sales/ + marketing/);
Phase 0 refactor complete; Marketing Analyzer Phase 1 build pending.

> **Milestone 2 (Marketing Analyzer) — Phase 0 refactor in PR, Phase 1 pending.**
> Design: [`MARKETING_ANALYZER_PLAN.md`](./MARKETING_ANALYZER_PLAN.md)
> Phase 0 execution plan: [`PHASE_0_REFACTOR_PLAN.md`](./PHASE_0_REFACTOR_PLAN.md)
> Phase 1 build starts after Phase 0 ships to both live VPSes.

> **Deploying this for the first time?** Read [`INSTALL.md`](./INSTALL.md)
> for a complete step-by-step guide. This file is for tracking *what's
> done vs. pending in the project itself*; INSTALL.md is for *how to
> run the project*.

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

All three migrations applied against live Supabase and verified end-to-end:

- `001_initial.sql` — enums, tables, indexes, triggers
- `002_views.sql` — `v_rep_performance_30d`, `v_cold_warm_comparison`,
  `v_therapist_mode_trend`, `v_weekly_objections`
- `003_weekly_views.sql` — `v_rep_performance_weekly`, `v_weekly_overview`,
  `v_top_objections_weekly`

### Inline-transcript webhook — added ✅ (commit `8dda9af`)

A second webhook endpoint `/webhooks/ghl/transcript-ready` accepts
GHL's "Transcript Generated" workflow trigger payload, which delivers
the transcript text inline. This eliminates the GHL API fetch step,
sidesteps the call-completed-vs-transcript-ready race, and works on
GHL workspaces where the transcript is exposed via merge tags but not
via the Conversations API. `process_call` was modified to detect inline
transcripts and skip the GHL fetch in that case.

### End-to-end validation — done ✅

Real curl payload → webhook → DB → Celery → Claude scoring → Slack
scorecard verified working in this session. Score: 7/10, 3 coaching
moments, 2 objections detected (price + spouse). User confirmed Slack
formatting is correct.

### Caddy reverse proxy infrastructure — added ✅ (commit `f5e9791`)

`infra/caddy/` is a standalone Caddy reverse-proxy project that fronts
every agent on the same VPS under a single hostname (`api.<DOMAIN>`)
with **path-based routing**. Salesagent is wired up at `/salesgrader/*`;
future agents (SDR, Sheets analyzer, etc.) drop in as additional
`handle_path` blocks in the Caddyfile with no DNS or cert work.

Salesagent's `docker-compose.yml` was updated to:
- Join the shared external `web` Docker network for Caddy access
- Bind host ports to `127.0.0.1` only (was `0.0.0.0`) so Redis, Flower,
  and the API are unreachable from outside the host except via Caddy

After VPS deploy, the GHL webhook URL becomes:
```
https://api.<DOMAIN>/salesgrader/webhooks/ghl/transcript-ready
```

See `infra/caddy/README.md` for the full host setup walkthrough.

---

### Step 11 — Deploy to VPS ✅ (deployed 2026-04-14)

**Hostinger VPS:** Ubuntu 24, IP `2.24.198.69`
**Domain:** `api.gogrowlabs.com` (A record → VPS IP)
**Layout:** `/srv/caddy/` (reverse proxy) + `/srv/salesagent/` (app)

- [x] Provision VPS, install Docker + Compose v2
- [x] `docker network create web`, firewall (80/443 + SSH)
- [x] DNS A record `api.gogrowlabs.com` → `2.24.198.69`
- [x] Caddy up with auto-TLS cert for `api.gogrowlabs.com`
- [x] Salesagent up — all 5 containers (api, worker, beat, redis, flower)
- [x] `curl https://api.gogrowlabs.com/salesgrader/health/ready` → `{"status":"ready",...}` ✅
- [x] Test curl → Claude scoring → Slack scorecard ✅
- [x] Weekly report tested via CLI ✅
- [ ] Connect GHL workflow webhook URL to production endpoint
- [ ] Make a real call through GHL → verify scorecard in `#sales-scorecards`

**Note:** `APP_ENV=development` is set because GHL doesn't natively
HMAC-sign webhook payloads. The webhook URL is private/unguessable.

### Phase 3 — Architectural simplification ✅ (shipped 2026-05-04)

Single ingestion model: `/webhooks/ghl/transcript-ready` is now the
only webhook endpoint. Lead-source attribution comes from UTM merge
tags in the payload (`utm_source/medium/campaign/content/term`)
instead of a follow-up GHL Contacts API call. Lead temperature is
computed from our own `calls` history. New clients no longer need
to issue a GHL Private Integration token.

**Removed:** `/ghl/call-completed` endpoint, `process_call` task,
`app/services/ghl_client.py`, `_enrich_from_contact` chain, `call_type`
column + enum, `recording_url` column, `ghl_conversation_id` column.
~250 lines deleted.

**Added:** migration `008_simplify_to_inline_only.sql`, five UTM columns,
`utm_source` → `lead_source` enum normalizer in the webhook handler,
DB-derived lead-temperature compute (catches returning leads more
accurately than GHL's `dateAdded`).

246 tests pass.

### Phase 2 — Management UI ✅ (shipped 2026-05-03)

Server-rendered dark-themed dashboard for the 3 leadership users
per client (CEO, Sales Manager, Client Manager). Stack: FastAPI +
Jinja2 + HTMX + Tailwind + Chart.js (all CDN — no JS toolchain).

**Pages live:**
- `/ui/` — Overview with 5 KPI cards, top performers / needs-coaching
  leaderboards (3-call qualification minimum), latest insights cards
  (sales / coaching / marketing), 30-day rep table, recent calls feed
- `/ui/calls` — filterable, paginated table (rep, outcome, source, window)
  with bookmarkable URL state
- `/ui/calls/:id` — full call detail: rep + lead + outcome with confidence
  + evidence quote, score grid, AI summary, therapist banner, win/loss
  moment, coaching moments + objections, full transcript
- `/ui/reps` — 30-day performance table per rep, click for detail
- `/ui/reps/:id` — per-rep stats, score trend chart, **coaching effectiveness
  check** (avg score before vs after each coaching moment), coaching
  history grouped by category, recent calls
- `/ui/sources` — last-week per-source close rate + score quality + top
  objections per source, plus 90-day cold-vs-warm comparison
- `/ui/objections` — top objections this week with per-source breakdown,
  30-day handling-quality rollup
- `/ui/therapist-mode` — trend table per rep per week, recent flagged
  calls with the AI's reason text
- `/ui/reports` — archived weekly reports (sales / coaching / marketing
  tabs) reading from the new `weekly_reports` table

**Infra additions:**
- `URL_PREFIX` env var for path-stripping reverse proxy (e.g. `/salesgrader`)
- `weekly_reports` table (migration 007) persists each Monday's Claude-
  generated reports so the UI archive doesn't need to re-run Claude
- Caddy basicauth gate on `/ui/*` (per ONBOARDING.md) — webhooks stay public
- 259 tests passing (94 new for UI routes, helpers, persistence)

## What's NOT done yet

**Hardening (recommended before heavy usage):**

- [ ] Lock down Flower behind Caddy basicauth or remove the service
- [ ] Enable Sentry (or another error-alerting story)
- [ ] Set up Anthropic spending alerts in the Console
- [ ] Verify Supabase backups are enabled and test a restore once

### Step 12 — Switch Claude scoring to tool-use API 🔒 deferred

The current prompt has explicit JSON schema specification, which gets
us to >99% schema compliance in practice. The architecturally correct
fix is to switch `app/services/claude_client.py` to use Anthropic's
tool-use feature, which forces 100% schema compliance at the SDK level.
~30 min refactor. Recommended after one or two real prompt drift
incidents make the value tangible.

### Step 13 — Admin UI 🔒 deferred

Deliberately not built. Real managers need to use Slack scorecards
for ~1 week of real volume before we know what a dashboard should
show. Building it before that point is guessing.

### Step 14 — Multi-CRM adapters 🔒 conditional

Currently the system is GHL-specific by name. The endpoint contract
itself is CRM-agnostic — any CRM that can POST JSON to a URL works
with zero code changes if you can configure the webhook body shape
to match (see INSTALL.md Appendix A). Only do this work if you
actually plan to deploy against a non-GHL CRM and need a per-CRM
adapter rather than relying on the CRM's webhook customization.

### Stale credential rotation (housekeeping) ⏳ verify

Three credentials were briefly leaked during this session's debugging
and the user said they were rotated. Worth verifying they're actually
revoked in the respective consoles:
- GHL Private Integration token `pit-cacc7f87-...`
- Supabase service key `sb_secret_yG6c28GlN4Sjc8dq...`
- Anthropic API key `sk-ant-api03-OJCMZmVX...`

---

## How to resume

1. **Read this file** to remember where you left off
2. **Read `INSTALL.md`** if you're deploying or onboarding someone new
3. **Optional: re-read `CLAUDE.md`** for coding conventions
4. **Work through the ⏳ pending checklist above** in order
5. **When ready for Claude Code,** just say "let's pick up where we left off"
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
