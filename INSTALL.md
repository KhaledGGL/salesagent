# Sales Call Analyzer — Installation Guide

> **Audience:** Anyone deploying this system for a sales team. Assumes
> comfort with the Linux command line, Docker, and basic networking.
> No prior knowledge of this codebase required.

This guide walks you from a blank server to a running production system
that ingests sales call transcripts, scores them with Claude, and posts
formatted scorecards to Slack — plus a weekly aggregated report.

---

## 1. What you're installing

A small, reliable pipeline:

```
                   ┌─────────────┐
   CRM webhook ──▶ │  FastAPI    │ ──▶ Postgres (calls table)
                   │  /webhooks  │           │
                   └─────────────┘           ▼
                                       ┌──────────┐
                                       │  Redis   │ ◀─── Celery beat (weekly cron)
                                       └──────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │ Celery worker   │
                                   │  process_call   │ ──▶ enrich from CRM contact
                                   │  score_call     │ ──▶ Claude API
                                   │  notify_scorecard│ ──▶ Slack
                                   │  generate_weekly_report ──▶ Slack
                                   └─────────────────┘
```

**Five containers**, one Postgres database (managed or self-hosted),
two external API dependencies (Claude, Slack), and one webhook source
(your CRM). Total runtime cost at low volume: under $30/month including
Anthropic usage for ~500 scored calls.

---

## 2. Compatibility: what your stack needs

**Be honest with yourself about these BEFORE starting** — three of them
are dealbreakers, and finding out at smoke test time is painful.

### 2.1 Mandatory

| Requirement | Why | If you don't have it |
|---|---|---|
| **A CRM (or telephony platform) that can POST a JSON webhook to a URL when a call ends** | This is how calls enter the system. | You can't use this system. Almost every modern CRM supports webhooks (GHL, HubSpot, Salesforce, Pipedrive, Close, Twilio, Aircall, Dialpad, RingCentral, etc.) so this is rarely a blocker. |
| **A way to get the call transcript** — either inline in the webhook body, or via a follow-up API call to the CRM | The system scores text, not audio. | See [Appendix B](#appendix-b-adapting-to-a-different-transcript-source) — you can wire in a transcription service (Deepgram / Whisper / AssemblyAI) as a preprocessing step. Adds ~$0.005/min and ~30 min of code work. |
| **A Slack workspace** with permission to install a bot | Default notification channel. | See [Appendix C](#appendix-c-replacing-slack-with-another-notification-channel) — the notifier is small and isolated; swapping for Discord, Teams, or email is a few hours of work. |
| **A Linux server with Docker installed** | The whole stack ships as Docker images. | A Mac/Windows machine works for evaluation but production should be Linux. |
| **An Anthropic API key with a spending cap** | This is what scores the calls. | No alternative — the system is built around Claude's reasoning quality on long-context conversations. |
| **A Postgres database** — managed (Supabase, Neon, RDS) or self-hosted | All persistent state lives here. | None — Postgres is universal. |

### 2.2 Optional

| Optional service | What it adds |
|---|---|
| **Sentry** | Error tracking, alerts on production failures |
| **Fly.io / Railway / Render account** | Managed hosting; alternative to self-managing the Linux server |
| **A domain + TLS certificate** | Required if you'll receive webhooks from a real CRM (not just localhost testing) |

### 2.3 What this system does NOT do

Be clear-eyed about the boundaries:

- ❌ **Does not record calls.** Your CRM/telephony platform must do that.
- ❌ **Does not transcribe audio out of the box.** It expects text. (See Appendix B for adding a transcription step.)
- ❌ **Does not have a web admin UI.** All output is in Slack. A dashboard is intentionally deferred until real usage informs what it should show.
- ❌ **Does not handle real-time call monitoring.** It scores completed calls, post-hoc, asynchronously (typically 15-30 seconds after the webhook fires).
- ❌ **Does not enforce per-tenant isolation.** This is a single-tenant deployment. Multi-tenant SaaS would require schema changes to add `tenant_id` columns and Row-Level Security.

---

## 3. Prerequisites

Before you start, gather these. **It's faster to gather everything upfront
than to context-switch mid-install.**

### 3.1 Accounts to create (free tiers work for most)

- [ ] **Postgres database** — Supabase free tier is the path of least resistance
- [ ] **Anthropic Console** account at https://console.anthropic.com — set a $50/month spending cap before generating any keys
- [ ] **Slack workspace** where you have admin permissions to install apps
- [ ] **Sentry** (optional) at https://sentry.io for error tracking
- [ ] **Hosting** — choose one:
  - Fly.io (recommended for solo deployment, managed multi-process)
  - Railway / Render (easier UI but pricier at steady state)
  - AWS / GCP / DigitalOcean (more control, more setup)
  - Your own Linux server (cheapest, most setup)

### 3.2 Server prerequisites (if self-hosting)

- Linux: Ubuntu 22.04+, Debian 12+, or any modern systemd distro
- 1 vCPU, 1 GB RAM minimum (2 GB recommended)
- 10 GB disk
- Docker 24+ and Docker Compose v2
- Git
- A static public IP **OR** a tunneling solution (Cloudflare Tunnel / ngrok) so your CRM can reach the webhook

Install Docker if not present:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER  # log out and back in for this to take effect
```

### 3.3 Knowledge prerequisites

You should be comfortable with:
- Editing config files via SSH or a code editor
- Reading Docker logs (`docker compose logs <service>`)
- Configuring webhooks in your CRM's admin panel
- Basic SQL (you'll run three migrations)

You do NOT need to know Python, Celery, or anything about the codebase
internals to deploy and operate this system.

---

## 4. Step-by-step installation

### 4.1 Get the code

```bash
git clone <your-fork-url> salesagent
cd salesagent
```

### 4.2 Set up Postgres + run migrations

**Path A — Supabase (recommended for first deploys):**

1. Sign up at https://supabase.com/dashboard
2. Click **New Project**, pick the closest region, save the database password
3. Wait for provisioning (~2 min)
4. Open the **SQL Editor** and run these three files in order, one at a time:
   - `001_initial.sql` — creates enums, tables, indexes, triggers
   - `002_views.sql` — creates 30-day rolling and objection-tracking views
   - `003_weekly_views.sql` — creates the views the weekly report task reads
5. Verify by running this query in the SQL Editor:
   ```sql
   select table_name, table_type
   from information_schema.tables
   where table_schema = 'public'
   order by table_type, table_name;
   ```
   You should see tables like `calls`, `reps`, `call_scores`, `coaching_moments`,
   `call_objections`, `rep_kpi_snapshots` AND views starting with `v_`
   (e.g., `v_rep_performance_30d`, `v_weekly_overview`).
6. Go to **Settings → API** and copy:
   - The **Project URL** → this is `SUPABASE_URL`
   - The **service_role secret** (NOT the anon/publishable key — the worker
     needs write access) → this is `SUPABASE_SERVICE_KEY`

**Path B — Self-hosted Postgres:**

1. Provision a Postgres 15+ database (RDS, Neon, your own server, whatever)
2. Run the three SQL files in order against your database:
   ```bash
   psql "$DATABASE_URL" -f 001_initial.sql
   psql "$DATABASE_URL" -f 002_views.sql
   psql "$DATABASE_URL" -f 003_weekly_views.sql
   ```
3. **Important:** The codebase currently uses the `supabase-py` client, which
   speaks PostgREST (Supabase's REST API), not raw Postgres. To use a
   non-Supabase database, you'd need to either (a) put PostgREST in front of
   your Postgres, or (b) refactor `app/db.py` to use `psycopg` or `asyncpg`
   directly. **Path A is dramatically less work.** Recommend Supabase unless
   you have a hard requirement against managed Postgres.

### 4.3 Provision external services

#### Anthropic API key

1. Go to https://console.anthropic.com → **Settings → Limits** → set a hard
   monthly spending cap. Recommended: **$50/month** for a team scoring
   500-1000 calls/month with Claude Sonnet 4.6.
2. Go to **API Keys** → **Create Key** → copy it. This is `ANTHROPIC_API_KEY`.
3. **Save it directly into your `.env` file** (which you'll create in Step 4.5).
   Do not paste it into chat, terminals you don't trust, or screenshots.

#### Slack app and channels

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Name it (e.g., "Sales Call Analyzer"), pick your workspace, click Create
3. In the left sidebar: **OAuth & Permissions** → scroll to **Scopes** →
   under **Bot Token Scopes**, add:
   - `chat:write` — post to channels the bot is in
   - `chat:write.public` — post to public channels without needing an explicit invite
4. Scroll back up on the same page → click **Install to Workspace** → **Allow**
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`). This is `SLACK_BOT_TOKEN`.
6. In Slack itself, create two channels:
   - `#sales-scorecards` — per-call scorecards land here
   - `#sales-reports` — weekly aggregated reports land here
7. **Invite the bot to both channels.** From inside each channel, type
   `/invite @your-bot-name`. This is the #1 most-skipped step that causes
   "the system seems to work but Slack is silent" failures.

#### Sentry (optional)

1. Sign up at https://sentry.io → create a new **Python** project
2. Copy the DSN from the project settings. This is `SENTRY_DSN`.
3. If you skip this, leave `SENTRY_DSN=` blank in `.env` — the system handles
   the absence cleanly.

### 4.4 Configure your CRM webhook

This is the most CRM-specific step. **The system is currently coded
against GoHighLevel's "Transcript Generated" workflow trigger**, but the
webhook contract is simple enough that any CRM that can POST JSON can use it.

#### Path A — GoHighLevel (primary supported CRM)

1. **Create a Private Integration** (sub-account → Settings → Private
   Integrations → New). Required scopes:
   - `conversations.readonly`
   - `conversations/message.readonly`
   - `contacts.readonly`

   Save the API key (starts with `pit-`) and the **Location ID**
   (visible in the sub-account URL). These become `GHL_API_KEY` and
   `GHL_LOCATION_ID` in `.env`.

2. **Build a workflow** in Automation → Workflows:
   - **Trigger:** "Transcript Generated" (or whichever transcript-ready
     trigger your GHL plan exposes)
   - **Action:** Webhook
     - **URL:** `https://<your-public-domain>/webhooks/ghl/transcript-ready`
     - **Method:** POST
     - **Body** (paste this exactly, the merge tags resolve at runtime):
       ```json
       {
         "call_sid": "{{transcript_generated.call_sid}}",
         "call_user_id": "{{transcript_generated.call_user_id}}",
         "call_duration": "{{transcript_generated.call_duration}}",
         "call_status": "{{transcript_generated.call_status}}",
         "call_from": "{{transcript_generated.call_from}}",
         "call_to": "{{transcript_generated.call_to}}",
         "call_transcript": "{{transcript_generated.call_transcript}}",
         "contact_id": "{{contact.id}}",
         "contact_name": "{{contact.name}}",
         "contact_email": "{{contact.email}}",
         "contact_phone": "{{contact.phone}}"
       }
       ```
     - **Headers:** none required for development; for production with HMAC
       signing, see Step 4.6 below
3. **Save and Publish** the workflow

#### Path B — Any other CRM (HubSpot, Close, Salesforce, Pipedrive, etc.)

Same idea, different UI. Configure a workflow / automation / webhook in
your CRM that fires when a call's transcript is ready, and have it POST
the **same JSON shape** as above to `/webhooks/ghl/transcript-ready`
(yes, the path still says "ghl" — rename it later if it bothers you;
the endpoint code is CRM-agnostic).

**Required JSON fields** (everything else is optional):
- `call_sid` — any string that's unique per call (used for deduplication)
- `call_user_id` — the rep / user / agent identifier in your CRM
- `call_transcript` — the actual transcript text (must be ≥50 chars)
- `contact_id` — the contact identifier in your CRM
- `call_status` — must equal `"completed"` (case-insensitive) or the call is filtered out

If your CRM uses different field names, you have two choices:
1. **Map them in the CRM's webhook config** (most CRMs let you rename fields when configuring the webhook body — easiest)
2. **Add an adapter route** in `app/webhooks/ghl.py` that translates your CRM's payload shape into the canonical one before processing — see [Appendix A](#appendix-a-adapting-to-a-different-crm)

### 4.5 Create and populate `.env`

```bash
cp .env.example .env
```

Then open `.env` in your editor and fill in every value. Use this template
as a checklist:

```bash
# ── App ──────────────────────────────────────────
APP_ENV=production                  # set to "development" only for local testing
SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(48))">
WEBHOOK_SECRET=<another random value, same command>

# ── Database ─────────────────────────────────────
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_KEY=<the service_role secret from Supabase Settings → API>

# ── Redis (leave as-is, docker-compose handles it) ────────
REDIS_URL=redis://redis:6379/0

# ── CRM (currently named GHL_* — see Appendix A to rename) ──
GHL_API_KEY=<your CRM API key>
GHL_LOCATION_ID=<your CRM location/account ID>

# ── AI ───────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...

# ── Slack ────────────────────────────────────────
SLACK_BOT_TOKEN=xoxb-...
SLACK_SCORECARD_CHANNEL=sales-scorecards
SLACK_REPORTS_CHANNEL=sales-reports

# ── Celery beat (weekly report schedule) ─────────
WEEKLY_REPORT_DAY=monday
WEEKLY_REPORT_HOUR=8

# ── Observability (optional) ─────────────────────
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.0
```

**⚠️ Never commit `.env`.** It's already in `.gitignore` — keep it that way.

### 4.6 Webhook signature verification (production-only)

When `APP_ENV=production`, the webhook endpoint enforces HMAC-SHA256
signature verification on every incoming request. The signature must be
in the `X-GHL-Signature` header, computed as:

```
HMAC-SHA256(WEBHOOK_SECRET, <raw_request_body>)
```

…and the result must be hex-encoded.

**Your CRM needs to be configured to send this header.** Three options:

1. **GHL native:** GoHighLevel does not natively HMAC-sign workflow webhooks
   as of this writing. You have two sub-options:
   - Use a middleware service (n8n, Pipedream, AWS Lambda) to receive the
     unsigned GHL webhook and re-emit it to our endpoint with the signature
   - Disable signature checking by leaving `APP_ENV=development` (less secure;
     only acceptable if your webhook URL is private/firewalled)
2. **Other CRMs (HubSpot, Salesforce, etc.):** Most enterprise CRMs support
   HMAC signing natively. Configure the secret to match `WEBHOOK_SECRET`.
3. **Cloudflare Tunnel + Access:** Put your webhook endpoint behind Cloudflare
   Access with mTLS or a service token. This sidesteps HMAC entirely by
   making the URL un-callable from outside the trusted CRM.

For first-deploy testing, **you can leave `APP_ENV=development`** to bypass
signature verification, then harden it later.

### 4.7 Deploy

Pick the deployment target that matches your operational comfort level.

#### Option A — Single Linux server (simplest)

```bash
cd salesagent
docker compose up -d --build
docker compose ps   # all five containers should be Up / healthy
```

That's it. The system is live on port 8000. The five containers are:
- `sales_api` — FastAPI on port 8000
- `sales_worker` — Celery worker (4 concurrent task slots)
- `sales_beat` — Celery beat scheduler (fires the weekly report cron)
- `sales_redis` — Redis broker with AOF persistence
- `sales_flower` — Celery monitoring UI on port 5555

To make the webhook reachable from your CRM, you need a public HTTPS URL
that points at port 8000. Three common patterns:
- **Caddy or nginx reverse proxy** with Let's Encrypt for TLS, in front
  of port 8000
- **Cloudflare Tunnel** — run `cloudflared` on the server, point a
  hostname at `localhost:8000`. Free, no inbound firewall holes needed.
- **Direct exposure** behind your existing load balancer

#### Option B — Fly.io (recommended for solo / small teams)

Fly.io has first-class support for multi-process apps, managed Redis,
and Dockerfile-based deploys. Cost at this scale: under $10/month.

```bash
brew install flyctl   # or: curl -L https://fly.io/install.sh | sh
fly auth login
fly launch --no-deploy   # creates fly.toml; edit it to define api/worker/beat as separate processes
fly redis create         # provision managed Redis, capture the URL
fly secrets set $(cat .env | xargs)   # upload .env as Fly secrets
fly deploy
```

You'll need to write a `fly.toml` that defines `api`, `worker`, and `beat`
as separate process groups sharing the same image. Fly's docs at
https://fly.io/docs/apps/processes/ show the pattern.

#### Option C — Railway

Railway autodetects the `Dockerfile` and lets you create three services
(api, worker, beat) from the same repo with different `Start Commands`.
Provision a Redis plugin from the marketplace. Set environment variables
through their UI.

#### Option D — AWS ECS / GCP Cloud Run / Kubernetes

For these, you're on your own — they're well-trodden Docker deploy targets
and not specific to this project. Use the existing `Dockerfile` as the
build target and deploy three task definitions (api / worker / beat).

### 4.8 First smoke test

Verify the system is alive and connected to all dependencies:

```bash
# Replace <your-host> with localhost OR your public domain
curl https://<your-host>/health
# Expect: {"status":"ok"}

curl https://<your-host>/health/ready
# Expect: {"status":"ready","checks":{"supabase":"ok","redis":"ok"}}
```

If `supabase` shows `fail: ...` — your `SUPABASE_URL` or `SUPABASE_SERVICE_KEY`
is wrong, or your Postgres firewall is blocking the worker IP.

If `redis` shows `fail: ...` — Redis container isn't running or `REDIS_URL`
is wrong.

Then run the **dry-run weekly report** to validate the Slack integration
without needing real call data:

```bash
docker compose exec worker python -m app.cli run-weekly-report
```

This should post a "No scored calls this week" message to `#sales-reports`.
**If this works, your full Slack + Celery + Postgres + Redis loop is verified.**

### 4.9 Send a test call through

The fastest way to validate the full pipeline (including Claude scoring)
is to POST a synthetic webhook with curl:

```bash
curl -s -X POST https://<your-host>/webhooks/ghl/transcript-ready \
  -H "Content-Type: application/json" \
  -d '{
    "call_sid":"CAtest_'"$(date +%s%N)"'",
    "call_user_id":"test_user_001",
    "call_duration":387,
    "call_status":"completed",
    "call_transcript":"<paste 3000+ chars of dialogue here — needs at least 6 exchanges and ~5 minutes of estimated call time or Claude will reject it as too short>",
    "contact_id":"test_contact_001",
    "contact_name":"Test Contact"
  }'
```

Expected response: `{"status":"accepted","call_id":"<uuid>"}`

Then watch the worker log:
```bash
docker compose logs worker -f --tail=30
```

Within 15-30 seconds you should see:
```
process_call started ...
Inline transcript detected ... — skipping GHL fetch
score_call started
score_call complete: overall=<some_number>
Posted main scorecard: ts=<slack_ts>
notify_scorecard complete
```

…and a real, formatted scorecard appears in `#sales-scorecards`.

**If you reach this point, the system is fully operational.** Wire up your
CRM webhook to the public URL and start receiving real calls.

---

## 5. Customizing the rubric

The Claude scoring prompt lives in `app/core/prompts.py`. The rubric is
written for high-ticket consultative B2C sales using NEPQ + AHM
methodology, but it's a single Python file you can rewrite completely.

**Things you can change in 5 minutes (no code changes elsewhere):**
- Scoring band descriptions (1-3, 4-6, 7-9, 10 criteria for each category)
- Therapist-mode detection rules
- Objection type classification
- Weighting of categories in the overall score
- AI summary length and tone
- Minimum transcript length

**Things you can change with moderate work** (touches schemas + DB + tests):
- Add a new scoring category (e.g., "follow-up commitment")
- Add a new field to coaching moments or objections
- Change the structure of `ai_summary` (e.g., split into "what worked" / "what failed")

**Things that require deeper refactoring:**
- Changing from 5 categories to N categories — touches the SQL views
  that drive weekly reports
- Switching to a different methodology entirely — requires rewriting the
  rubric from scratch and recalibrating expected scores

After any prompt change, restart the worker:
```bash
docker compose restart worker beat
```
Celery loads modules at startup and caches them; a bind mount alone is not
enough to pick up prompt changes.

---

## 6. Operations runbook

### 6.1 Reading logs

```bash
docker compose logs api -f --tail=50          # webhook receiver
docker compose logs worker -f --tail=50       # scoring + Slack posting
docker compose logs beat -f --tail=20         # weekly cron
docker compose logs -f                        # everything at once
```

### 6.2 Replaying a failed call

If a call ended up in `status='failed'` (e.g., Claude API outage,
transient Slack failure), you can replay it via the CLI:

```bash
docker compose exec worker python -m app.cli replay --call-id <uuid>
```

This re-enqueues `process_call` for that call, which inherits all the
normal retry semantics. Idempotent — replaying a successful call just
re-runs scoring (and possibly re-posts to Slack, which is fine).

### 6.3 Manually triggering the weekly report

```bash
docker compose exec worker python -m app.cli run-weekly-report
```

Useful if Celery beat is paused, or you want to force a mid-week update.

### 6.4 Flower (Celery monitoring UI)

Open `http://<your-host>:5555` to see real-time task queues, worker
status, success/failure rates. **Lock this down** — it's an unauthenticated
UI by default. In production, put it behind an auth proxy or take the
port out of the compose file entirely.

### 6.5 Scaling

The system was designed for low-medium volume (under 10,000 scored
calls/month). Scaling levers:

- **More worker concurrency:** edit the `worker` command in
  `docker-compose.yml`, change `--concurrency=4` to `--concurrency=8` (or
  whatever your CPU allows). Each Celery worker process can score
  ~1 call per 15-30s.
- **More worker containers:** scale horizontally with `docker compose up
  -d --scale worker=3` or by deploying multiple worker hosts pointing at
  the same Redis broker.
- **Postgres connection pool:** Supabase handles this automatically.
  For self-hosted Postgres, put PgBouncer in front.
- **Redis persistence:** AOF is enabled by default. For very high
  throughput, consider disabling AOF and accepting that in-flight tasks
  are lost on Redis crash.

### 6.6 Cost monitoring

The two costs that scale with usage are:
- **Anthropic API** — Claude Sonnet 4.6 at the volume of input/output
  used here is roughly $0.05-$0.10 per scored call. Set a hard monthly
  cap in the Anthropic Console.
- **Postgres** — negligible at this scale; Supabase free tier is fine
  up to ~50,000 calls.

The other costs (Slack, Redis, FastAPI compute) are essentially free.

---

## 7. Production hardening checklist

Before pointing real customer calls at this system:

- [ ] `APP_ENV=production` set in `.env`
- [ ] Webhook signature verification configured AND tested with a real
      signed payload from your CRM (or explicitly accepted as a risk
      because the URL is firewalled / Cloudflare Access protected)
- [ ] Anthropic spending cap set in the console
- [ ] All five containers restart automatically (`restart: unless-stopped`
      is the default in `docker-compose.yml` — verify it's still there
      if you customized)
- [ ] Sentry DSN configured (or you have another error-alerting story)
- [ ] Database backups enabled (Supabase: free tier includes daily
      backups; self-hosted: configure `pg_dump` cron)
- [ ] `.env` is on disk only on the production server, not in git, not
      in screenshots, not in chat
- [ ] Slack bot is invited to BOTH channels and you've verified posting
      with the smoke test
- [ ] Flower (`:5555`) is either firewalled, behind auth, or removed
- [ ] You've read the worker log during one real test call and confirmed
      no surprising warnings
- [ ] You have a runbook entry for "what to do if Claude API is down"
      (answer: tasks retry with backoff for ~10 minutes, then end up
      in `status='failed'` and can be replayed via the CLI)

---

## Appendix A: Adapting to a different CRM

The system is currently coded against GoHighLevel's webhook payload shape,
but the integration surface is small and well-isolated. Here's what's
GHL-specific and what's not:

### Files that are CRM-agnostic (don't need to change)
- `app/workers/tasks.py` — pipeline orchestration
- `app/services/claude_client.py` — scoring
- `app/services/slack_client.py` — notifications
- `app/core/prompts.py` — rubric
- `app/core/slack_blocks.py` — formatting
- `app/main.py` — FastAPI app
- All migrations and views

### Files that ARE GHL-specific
- `app/webhooks/ghl.py` — webhook receiver routes (path includes "ghl")
- `app/services/ghl_client.py` — used only by the older `call-completed`
  endpoint to fetch transcripts. The newer `transcript-ready` endpoint
  receives transcripts inline and never touches this file.
- `schemas.py` — `GHLWebhookPayload` and `GHLTranscriptReadyPayload`
  (field names mirror GHL's merge tag namespace)
- `config.py` — `GHL_API_KEY` and `GHL_LOCATION_ID` env vars

### Two paths to support a new CRM

**Path 1 — Reuse the existing endpoint, map fields in the CRM's webhook config**

If your CRM lets you customize the webhook body (most do), configure it
to send the exact same JSON shape the existing endpoint expects:

```json
{
  "call_sid": "<your CRM's unique call ID>",
  "call_user_id": "<your CRM's rep ID>",
  "call_transcript": "<the transcript text>",
  "call_status": "completed",
  "contact_id": "<your CRM's contact ID>",
  "call_duration": 387,
  "contact_name": "<optional>",
  "contact_email": "<optional>",
  "contact_phone": "<optional>"
}
```

**Zero code changes**, point the webhook at `/webhooks/ghl/transcript-ready`,
done. (Yes, the path still says "ghl" — rename it via a symlink route or
just live with the legacy name.)

**Path 2 — Add a new adapter endpoint**

For CRMs that can't customize the webhook body shape, add a new route in
`app/webhooks/ghl.py` (or a new file `app/webhooks/<crm>.py` and register
it in `app/main.py`) that:

1. Accepts the CRM's native payload shape
2. Translates it to the canonical fields
3. Calls the same downstream insert + dispatch logic

Template:

```python
@router.post("/your-crm/transcript-ready", status_code=200)
async def your_crm_webhook(request: Request):
    body = await request.json()

    # Translate the CRM's native fields to canonical names
    canonical = {
        "call_sid": body["theirCallId"],
        "call_user_id": body["theirRepId"],
        "call_transcript": body["theirTranscriptField"],
        "contact_id": body["theirContactId"],
        "call_status": "completed",  # or map from their status enum
        "call_duration": body.get("theirDurationField"),
        "contact_name": body.get("theirContactNameField"),
    }

    # Reuse the validated Pydantic model and the rest of the pipeline
    payload = GHLTranscriptReadyPayload(**canonical)
    # ... copy the rep upsert + call insert + process_call.delay() block
    # from ghl_transcript_ready, or refactor it into a shared helper
```

If you support more than two CRMs, refactor the rep-upsert and call-insert
logic into a shared `_persist_call_and_dispatch(payload)` helper so each
adapter is just the translation layer.

### Renaming the env vars

If "GHL" in the env var names bothers you, rename them in `config.py`:

```python
# Before:
ghl_api_key: str
ghl_location_id: str

# After:
crm_api_key: str
crm_location_id: str
```

…and update `.env.example`. This is purely cosmetic — the system runs the
same regardless of variable names.

---

## Appendix B: Adapting to a different transcript source

The system requires text. If your CRM/telephony only provides audio
recordings, you need a transcription preprocessing step.

### Recommended: Deepgram

- Best price/quality for English phone audio (~$0.0043/min)
- Excellent speaker diarization (separates rep vs. prospect)
- Streaming + batch APIs
- Sub-second latency on batch transcription of 10-minute calls

### Implementation sketch

1. **Add the Deepgram SDK** to `requirements.txt`:
   ```
   deepgram-sdk==3.7.0
   ```
2. **Create a new service** at `app/services/transcription.py`:
   ```python
   from deepgram import DeepgramClient, PrerecordedOptions
   from config import settings

   _client = DeepgramClient(settings.deepgram_api_key)

   def transcribe_url(audio_url: str) -> str:
       options = PrerecordedOptions(
           model="nova-3",
           smart_format=True,
           diarize=True,
           punctuate=True,
       )
       resp = _client.listen.rest.v("1").transcribe_url(
           {"url": audio_url}, options
       )
       # Build a "Speaker 0: ... \n Speaker 1: ..." style transcript
       return _format_diarized_transcript(resp)
   ```
3. **Modify `process_call`** in `app/workers/tasks.py` to call this service
   when `transcript` is empty but `recording_url` is set:
   ```python
   if not existing_transcript and existing_recording_url:
       from app.services.transcription import transcribe_url
       transcript = transcribe_url(existing_recording_url)
       _update_call(call_id, transcript=transcript)
   ```
4. **Add `DEEPGRAM_API_KEY`** to `config.py`, `.env.example`, and your
   running `.env`
5. **Add cost monitoring** to your Anthropic monitoring — Deepgram bills
   per audio minute, separate from Claude's per-token billing

Total work: ~30-60 minutes including testing.

### Alternative: OpenAI Whisper API

Slightly cheaper (~$0.006/min) but worse on phone audio noise, no native
diarization. Use only if you're already in the OpenAI ecosystem.

### Alternative: Self-hosted faster-whisper

Free in compute terms but adds GPU/CPU complexity and operational burden.
Only worth it at very high volume (>100,000 minutes/month).

---

## Appendix C: Replacing Slack with another notification channel

The Slack notifier is isolated in two files:
- `app/services/slack_client.py` — the API client
- `app/core/slack_blocks.py` and `app/core/report_blocks.py` — message
  formatting (Slack's "Block Kit" structured layout)

To replace Slack with Discord, Teams, email, or webhook-to-anywhere:

1. **Create a new notifier module** (e.g., `app/services/discord_client.py`)
   that exposes the same `post_message(channel, blocks, text, thread_ts=None)`
   signature
2. **Create a new formatter** that produces output in your destination's
   native format (Discord embeds, Teams MessageCards, plain HTML email,
   whatever)
3. **Edit `app/workers/tasks.py::notify_scorecard`** to import from your
   new module instead of `slack_client`
4. **Replace `SLACK_*` env vars** in `config.py` with the equivalents for
   your channel

The pipeline orchestration doesn't change — you're swapping a leaf node.
Total work depends on how rich a layout you want; a basic email notifier
is ~2 hours, a Discord embed equivalent to the Slack scorecard is ~4 hours.

---

## Appendix D: Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health/ready` returns `supabase: fail: SupabaseException` | Wrong key or URL, or `supabase-py` version too old for the new `sb_secret_*` key format | Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY`. Make sure `requirements.txt` pins `supabase>=2.28.0`. |
| `/health/ready` returns `redis: fail` | Redis container not running, or `REDIS_URL` wrong | `docker compose ps` to check; restart with `docker compose up -d redis` |
| Webhook returns 500 with `json.loads` traceback | Body has unescaped newlines or quotes (most common with hand-written curl heredocs) | The endpoint has a tolerant parser that should handle this; if it still fails, check the API logs for `transcript-ready: could not parse body` and paste the `preview` field |
| Webhook returns 422 | Pydantic validation failure | Check API logs for `transcript-ready payload validation error` — the `received_keys` field tells you exactly which fields the payload had |
| `score_call` fails with `validation errors for ScorecardOutput` | Claude returned a JSON shape that doesn't match the schema | The prompt has explicit schema enforcement; if it still drifts, switch to Anthropic tool use API (recommended long-term fix) |
| `notify_scorecard` succeeds in logs but no message in Slack | Bot not invited to the channel | `/invite @your-bot-name` from inside the channel |
| `notify_scorecard` returns `channel_not_found` | Channel name in `.env` is wrong (typo, or includes `#` prefix) | `SLACK_SCORECARD_CHANNEL=sales-scorecards` (no `#`, no `@`) |
| Worker is in restart loop | Usually a config error | `docker compose logs worker` and read the first error |
| Beat is in restart loop with `Permission denied: celerybeat-schedule` | Celery beat trying to write to a non-writable directory | `docker-compose.yml` should have `--schedule=/tmp/celerybeat-schedule` in the beat command |
| All five containers up but no traffic | Webhook URL wrong in CRM, or your reverse proxy is dropping the request | Check ngrok / Cloudflare logs first, then API logs |

---

## Appendix E: Architecture rationale (for the curious)

A few non-obvious design decisions worth understanding:

- **Sonnet 4.6 for scoring, not Opus.** Structured extraction with a clear
  rubric doesn't need Opus-level reasoning. Sonnet is ~5x cheaper with
  >95% quality parity on this task. Verified empirically.
- **Lead enrichment happens in `process_call`, not `score_call`.** Scoring
  is then a pure function of (transcript + metadata) and trivially
  unit-testable. Side effects stay in the orchestration layer.
- **`notify_scorecard` is a separate Celery task**, not inlined into
  `score_call`. A Slack outage cannot corrupt a successfully-scored
  call's status. Replays of a notification don't re-spend Claude tokens.
- **SQL views own "last week" date math, not Python.** Timezone and
  week-boundary bugs live in one place (`002_views.sql`), not scattered
  across task code where they'd be a nightmare to debug.
- **3-call qualification threshold** for top performers / needs coaching
  in weekly reports. Prevents single-outlier calls from dominating
  rankings.
- **Redis AOF persistence** in docker-compose. Queue survives restarts;
  without this, in-flight scoring jobs are lost on `docker compose restart`.
- **Readiness check separate from liveness.** `/health` is cheap (no
  network) and used by container orchestrators for "is this process
  alive". `/health/ready` actually round-trips Supabase and Redis and
  is used to decide whether to route traffic. Pods can be alive but
  not ready (e.g., during database failover) and orchestrators handle
  this correctly.
- **Replay CLI uses `.delay()` not direct execution.** Inherits normal
  Celery retry semantics; the operator just enqueues, the system does
  the rest.
- **Inline-transcript webhook bypasses the GHL fetch step.** When the
  CRM delivers the transcript inline, there's no point making a follow-up
  API call. `process_call` detects this case and skips the fetch.

---

## Getting help

If you hit something this guide doesn't cover, the most useful debugging
artifacts to capture are:

1. **The exact log line** from `docker compose logs worker --tail=200` or
   `docker compose logs api --tail=200` showing the failure
2. **The output of `docker compose ps`** showing container states
3. **The output of `curl <your-host>/health/ready`** showing dependency status
4. **Your `.env` file with all secret values redacted** (i.e., showing
   which keys are populated, not their values)

With those four pieces of information, almost any failure can be
diagnosed in one round trip.
