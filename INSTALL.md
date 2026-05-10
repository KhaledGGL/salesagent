# Sales Call Analyzer — Installation Guide

> **Audience:** Anyone deploying this system for a new client. Assumes
> comfort with the Linux command line, Docker, and basic networking.
> No prior knowledge of this codebase required.

> **Two routing models exist for this project — pick before you start:**
>
> 1. **Per-client hostname (recommended for new deployments)** — each
>    tenant brings their own domain (`analyzer.acme.com`,
>    `sales.client2.io`). Caddy issues a separate Let's Encrypt cert per
>    host. No URL prefix in `.env`.
>    👉 Use [`NEW_VPS_ONBOARDING.md`](./NEW_VPS_ONBOARDING.md) for the
>    end-to-end walkthrough; this file (INSTALL.md) is mostly
>    interchangeable but the URLs below assume Model 2.
>
> 2. **Shared host with path prefix (this document's default)** — all
>    tenants live under `api.<DOMAIN>/<slug>/*`. One cert covers
>    everything; each app sets `URL_PREFIX=/<slug>`. Used by the
>    existing `salesgrader` deployment.
>
> The `infra/caddy/Caddyfile` ships templates for both. You can mix
> models on the same host.

This guide walks you from zero to a running production system that
ingests sales call transcripts, scores them with Claude (NEPQ/AHM
methodology), and posts to Slack:

- **Per-call scorecards** — 5-category breakdown + coaching moments + objections
- **Weekly sales report** — KPIs, top performers, needs coaching, top objections
- **Weekly coaching lesson** — Claude-synthesized training from real call data
- **Weekly marketing intelligence** — messaging angles, source quality, positioning gaps

---

## 1. What you're installing

```
                   ┌─────────────┐
   CRM webhook ──▶ │  FastAPI    │ ──▶ Postgres (calls table)
                   │  /webhooks  │           │
                   └─────────────┘           ▼
                                       ┌──────────┐
                                       │  Redis   │ ◀─── Celery beat (weekly crons)
                                       └──────────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │ Celery worker    │
                                   │  score_call      │ ──▶ Claude API
                                   │  notify_scorecard│ ──▶ Slack
                                   │  weekly_report   │ ──▶ Slack (Monday :00)
                                   │  coaching_lesson │ ──▶ Slack (Monday :05)
                                   │  marketing_intel │ ──▶ Slack (Monday :10)
                                   └─────────────────┘
```

**Five containers**, one Postgres database (Supabase), two external
API dependencies (Claude, Slack), and one webhook source (your CRM).
Total runtime cost at low volume: under $30/month including Anthropic
usage for ~500 scored calls.

---

## 2. Prerequisites — gather BEFORE starting

### 2.1 Accounts to create

- [ ] **Supabase** project (free tier) — https://supabase.com/dashboard
- [ ] **Anthropic Console** account — https://console.anthropic.com — set a $50/month spending cap before generating keys
- [ ] **Slack workspace** where you have admin permissions to install apps
- [ ] **VPS** — any provider (Hostinger, DigitalOcean, Hetzner, etc.), Ubuntu 22.04+, 2 GB RAM recommended
- [ ] **Domain** — you need a domain to point at the VPS (e.g., `api.clientdomain.com`)

### 2.2 From the client

- [ ] CRM API credentials (GHL: Private Integration key + Location ID)
- [ ] Slack workspace access (to install the bot)
- [ ] Business description for tailored scoring (optional but recommended)

### 2.3 What this system does NOT do

- Does not record calls — the CRM/telephony platform must do that
- Does not transcribe audio — it expects text (see [Appendix B](#appendix-b-adapting-to-a-different-transcript-source) to add transcription)
- Does not have a web admin UI — all output is in Slack
- Does not handle real-time call monitoring — it scores completed calls asynchronously (~15-30 seconds)

---

## 3. Step-by-step installation

### 3.1 VPS setup

SSH into the VPS:

```bash
ssh root@<vps-ip>

# Update system
apt update && apt upgrade -y

# Install Docker + Compose v2
curl -fsSL https://get.docker.com | sh

# Verify
docker --version
docker compose version

# Create shared Docker network for Caddy
docker network create web

# Firewall: allow SSH + HTTP/HTTPS
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Install git
apt install -y git
```

### 3.2 DNS

Add an A record at the client's domain registrar:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `api` | `<vps-ip>` | 14400 (default) |

Verify propagation:

```bash
dig api.<domain> +short
# Should return the VPS IP
```

### 3.3 Set up Caddy (reverse proxy + TLS)

```bash
# Clone the repo
git clone https://github.com/KhaledGGL/salesagent.git /srv/salesagent

# Copy Caddy config
cp -r /srv/salesagent/infra/caddy /srv/caddy

# Create Caddy .env
cat > /srv/caddy/.env << EOF
DOMAIN=<client-domain.com>
ACME_EMAIL=<your-email@example.com>
EOF

# Start Caddy
cd /srv/caddy
docker compose up -d

# Verify cert issuance
docker compose logs -f caddy
# Wait for "certificate obtained successfully", then Ctrl+C

# Test
curl https://api.<domain>/
# Should return: "Caddy reverse proxy OK. Use /<agent>/<path> to reach a service."
```

### 3.4 Set up Supabase + run migrations

1. Go to https://supabase.com/dashboard → **New Project**
2. Pick the closest region, save the database password
3. Wait for provisioning (~2 min)
4. Open **SQL Editor** and run these four files in order, one at a time:
   - `001_initial.sql` — enums, tables, indexes, triggers
   - `002_views.sql` — 30-day rolling + objection-tracking views
   - `003_weekly_views.sql` — weekly report views
   - `004_coaching_marketing_views.sql` — coaching lesson + marketing intel views
5. Verify:
   ```sql
   select table_name, table_type
   from information_schema.tables
   where table_schema = 'public'
   order by table_type, table_name;
   ```
   You should see tables (`calls`, `reps`, `call_scores`, `coaching_moments`,
   `call_objections`, `rep_kpi_snapshots`) and views starting with `v_`.
6. Go to **Settings → API** and copy:
   - **Project URL** → this is `SUPABASE_URL`
   - **service_role secret** (NOT the anon key) → this is `SUPABASE_SERVICE_KEY`

### 3.5 Set up Anthropic API key

1. Go to https://console.anthropic.com → **Settings → Limits** → set a
   hard monthly spending cap (recommended: $50/month for 500-1000 calls)
2. Go to **API Keys** → **Create Key** → copy it. This is `ANTHROPIC_API_KEY`

### 3.6 Set up Slack app

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. Name it (e.g., "Sales Call Analyzer"), pick the client's workspace
3. **OAuth & Permissions** → **Bot Token Scopes**, add:
   - `chat:write`
   - `chat:write.public`
4. Click **Install to Workspace** → **Allow**
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`). This is `SLACK_BOT_TOKEN`
6. In Slack, create these channels:
   - `#sales-scorecards` — per-call scorecards
   - `#sales-reports` — weekly reports, coaching lessons, marketing intel
7. **Invite the bot to both channels:**
   `/invite @your-bot-name` from inside each channel.
   This is the #1 most-skipped step that causes "everything works but Slack is silent".

### 3.7 Set up GHL (or other CRM)

#### GoHighLevel

The current ingestion model is the inline-transcript webhook with UTM
merge tags — **no GHL Private Integration / API key is required.** All
attribution comes from the webhook payload itself (utm_source, _medium,
_campaign, _content, _term passed via merge tags from the contact's
attribution source). Lead temperature is computed from our own DB.

You only need to configure the GHL workflow webhook (Step "GHL workflow"
in the post-deploy section). See ONBOARDING.md for the body shape and
the merge tags to plug in.

#### Any other CRM

Configure a webhook that fires when a call transcript is ready, POSTing
this JSON shape to `/webhooks/ghl/transcript-ready`:

```json
{
  "call_sid": "<unique per call>",
  "call_user_id": "<rep ID in your CRM>",
  "call_transcript": "<full transcript text, ≥50 chars>",
  "call_status": "completed",
  "contact_id": "<contact ID>",
  "call_duration": 387,
  "contact_name": "<optional>",
  "contact_email": "<optional>",
  "contact_phone": "<optional>"
}
```

Zero code changes needed — just map the fields in your CRM's webhook config.

### 3.8 Create and populate `.env`

```bash
cd /srv/salesagent
cp .env.example .env
nano .env
```

Fill in every value:

```bash
# ── App ──────────────────────────────────────────
APP_ENV=development                 # use "development" — GHL doesn't HMAC-sign
SECRET_KEY=<generate: openssl rand -hex 32>
WEBHOOK_SECRET=<generate: openssl rand -hex 32>

# ── Supabase ─────────────────────────────────────
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=<service_role secret>

# ── Redis (leave as-is) ─────────────────────────
REDIS_URL=redis://redis:6379/0

# ── GHL — OPTIONAL (no longer required) ─────────
# Inline-transcript webhook + UTM merge tags carries everything.
# Leave blank unless you re-introduce a GHL Contacts API integration.
# GHL_API_KEY=
# GHL_LOCATION_ID=

# ── Anthropic ────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...

# ── Slack ────────────────────────────────────────
SLACK_BOT_TOKEN=xoxb-...
SLACK_SCORECARD_CHANNEL=sales-scorecards
SLACK_REPORTS_CHANNEL=sales-reports
SLACK_MARKETING_CHANNEL=sales-reports

# ── Business context (optional) ─────────────────
# Leave blank for generic analysis. Fill in for
# offer-specific scoring and coaching.
BUSINESS_CONTEXT=We are a digital marketing agency selling monthly retainer packages ($2500-$5000/mo) to local service businesses. Our main offer is lead generation via Meta and Google Ads. Sales cycle is typically 1-2 calls.

# ── Celery beat schedule ─────────────────────────
WEEKLY_REPORT_DAY=monday
WEEKLY_REPORT_HOUR=8

# ── Observability (optional) ─────────────────────
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.0
```

**Never commit `.env`** — it's in `.gitignore`.

### 3.9 Deploy

```bash
cd /srv/salesagent
docker compose up -d --build
```

Wait for the build to finish (~2-3 minutes first time), then verify:

```bash
# All 5 containers should be Up / healthy
docker compose ps

# Health check
curl https://api.<domain>/salesgrader/health/ready
# Expect: {"status":"ready","checks":{"supabase":"ok","redis":"ok"}}
```

### 3.10 First smoke test

**Test the weekly report (validates Slack + Celery + Postgres + Redis):**

```bash
docker compose exec worker python -m app.cli run-weekly-report
```

Should post a "No scored calls this week" message to `#sales-reports`.

**Test the full pipeline (validates Claude scoring):**

```bash
curl -s -X POST https://api.<domain>/salesgrader/webhooks/ghl/transcript-ready \
  -H "Content-Type: application/json" \
  -d '{
    "call_sid": "test-deploy-001",
    "call_user_id": "test-rep-001",
    "call_transcript": "Hey thanks for calling in, what can I help you with today?\nYeah so I saw your ad on Facebook about the marketing program and I wanted to learn more.\nAwesome, glad you reached out. So before I go into anything, can I ask what made you click on that ad? What caught your attention?\nHonestly we have been struggling to get new clients for the past few months and it is getting really frustrating.\nI can imagine. How long has that been going on?\nProbably like four or five months now. We used to get referrals pretty consistently but that dried up.\nAnd what have you tried so far to fix it?\nWe did some Google Ads for a while but it was expensive and the leads were terrible. We also tried posting on social media but nobody really engages.\nSo you have spent money and time and still no results. How is that affecting the business right now?\nIt is stressful honestly. We had to let one person go last month because revenue was down.\nThat is tough. And if nothing changes in the next three to six months, where do you see things heading?\nI mean we would probably have to downsize more or I would have to go back to doing everything myself which I really do not want.\nMakes sense. So let me share how we typically help businesses in your situation. We build a lead generation system using paid ads and email outreach that targets decision makers in your industry. Most of our clients start seeing qualified leads within the first 30 days.\nThat sounds great but how much does it cost?\nGood question. Our program starts at 3000 per month. But based on what you just told me about the revenue you are losing every month without a system, the ROI usually pays for itself pretty quickly. What do you think?\nThat is more than I was expecting. I need to talk to my wife about it first.\nTotally understand. When you talk to her, what do you think her main concern would be?\nProbably just the money. We have been burned before by agencies that promised results and did not deliver.\nThat makes sense and I hear that a lot. That is actually why we do month to month, no long term contracts. You can see results before you commit further. Would that help address that concern?\nYeah that actually does help. Let me talk to her tonight and I will call you back tomorrow.\nSounds good. I will send you over a quick summary of what we discussed so you can share it with her. What is the best email to send that to?\nYou can send it to mike@example.com.\nPerfect. Talk to you tomorrow Mike.",
    "call_status": "completed",
    "contact_id": "test-contact-001",
    "call_duration": 380,
    "contact_name": "Mike Johnson",
    "contact_email": "mike@example.com",
    "contact_phone": "+15559876543"
  }'
```

Expected: `{"status":"accepted","call_id":"<uuid>"}`

Check `#sales-scorecards` in Slack — a scorecard should appear within 15-30 seconds.

**Test coaching lesson and marketing intel:**

```bash
# These need call data from the previous week. Backdate the test call's
# called_at in Supabase to last week if needed, then run:
docker compose exec worker python -m app.cli run-coaching-lesson
docker compose exec worker python -m app.cli run-marketing-intel
```

### 3.11 Connect GHL workflow

1. In GHL: **Automation → Workflows → New Workflow**
2. **Trigger:** "Transcript Generated"
3. **Action:** Webhook
   - **URL:** `https://api.<domain>/salesgrader/webhooks/ghl/transcript-ready`
   - **Method:** POST
   - **Body:**
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
4. **Save and Publish** the workflow
5. Make a real test call → verify scorecard in Slack

**If the scorecard appears, the system is fully operational.**

---

## 4. Weekly reports schedule

Three reports fire automatically every Monday (configurable via env vars):

| Time | Report | Slack Channel | What it shows |
|------|--------|---------------|---------------|
| :00 | Sales Report | `#sales-reports` | KPIs, close rate, top performers, needs coaching, top objections |
| :05 | Coaching Lesson | `#sales-reports` | Best/worst moments by category, NEPQ-specific advice, weekly focus |
| :10 | Marketing Intel | `#sales-reports` (or `SLACK_MARKETING_CHANNEL`) | Messaging angles, source quality, prequal recs, positioning gaps |

**Manual trigger anytime:**

```bash
docker compose exec worker python -m app.cli run-weekly-report
docker compose exec worker python -m app.cli run-coaching-lesson
docker compose exec worker python -m app.cli run-marketing-intel
```

---

## 5. Customizing per client

### Business context (most important)

The `BUSINESS_CONTEXT` env var in `.env` gets injected into all Claude
prompts. This is how you make scoring, coaching, and marketing insights
specific to a client's business.

**Examples:**

```
# Marketing agency
BUSINESS_CONTEXT=We are a digital marketing agency selling monthly retainer packages ($2500-$5000/mo) to local service businesses. Our main offer is lead generation via Meta and Google Ads. Sales cycle is typically 1-2 calls. Common competitors: GoHighLevel resellers, local agencies.

# Coaching business
BUSINESS_CONTEXT=We sell a 12-week high-ticket coaching program ($8,000) for B2B founders. Calls are discovery + treatment plan. Main objections are price and time commitment. We position on ROI and accountability.

# SaaS company
BUSINESS_CONTEXT=We sell a B2B SaaS platform for inventory management ($500-$2000/mo). Demo calls are 30 minutes. Main competitors: TradeGecko, Cin7. We win on ease of use and customer support.
```

Leave blank for generic sales analysis that works across any industry.

### Scoring rubric

The Claude scoring prompt is in `app/core/prompts.py`. You can change:
- Scoring band descriptions (what counts as a 7 vs a 9)
- Therapist-mode detection rules
- Objection type classifications
- Category weighting in the overall score
- AI summary tone and length

After any prompt change:
```bash
docker compose restart worker beat
```

### Slack channels

Override in `.env`:
```
SLACK_SCORECARD_CHANNEL=custom-scorecards
SLACK_REPORTS_CHANNEL=custom-reports
SLACK_MARKETING_CHANNEL=marketing-team
```

### Report schedule

```
WEEKLY_REPORT_DAY=tuesday
WEEKLY_REPORT_HOUR=9
```

---

## 6. Operations

### Reading logs

```bash
docker compose logs api -f --tail=50          # webhook receiver
docker compose logs worker -f --tail=50       # scoring + Slack posting
docker compose logs beat -f --tail=20         # weekly cron
docker compose logs -f                        # everything at once
```

### Replaying a failed call

```bash
docker compose exec worker python -m app.cli replay-scoring <call-uuid>
docker compose exec worker python -m app.cli replay-notification <call-uuid>
```

### Updating the code

```bash
cd /srv/salesagent
git pull origin master
docker compose up -d --build
```

### Scaling

- **More concurrency:** change `--concurrency=4` to `8` in `docker-compose.yml` worker command
- **More workers:** `docker compose up -d --scale worker=3`
- **Cost monitoring:** Claude Sonnet 4.6 ≈ $0.05-$0.10 per scored call. Set a hard monthly cap in Anthropic Console.

---

## 7. Production hardening checklist

Before pointing real customer calls at this system:

- [ ] Anthropic spending cap set in the console
- [ ] All five containers restart automatically (`restart: unless-stopped`)
- [ ] Sentry DSN configured (or you have another error-alerting story)
- [ ] Database backups enabled (Supabase free tier includes daily backups)
- [ ] `.env` is on disk only, not in git, not in screenshots, not in chat
- [ ] Slack bot is invited to ALL channels
- [ ] Flower (`:5555`) is either firewalled, behind auth, or removed
- [ ] You've watched the worker log during a real test call and confirmed no warnings
- [ ] Supabase service key has been rotated if it was ever pasted in chat

---

## Appendix A: Adapting to a different CRM

The system is coded against GHL's webhook payload shape, but the
integration surface is small. Any CRM that can POST JSON to a URL works.

### Zero code changes (recommended)

Configure your CRM's webhook to send the exact JSON shape the endpoint
expects (see Step 3.7). Map your CRM's field names to the canonical names
in the webhook config UI.

### Custom adapter (if CRM can't customize webhook body)

Add a new route in `app/webhooks/ghl.py` that translates your CRM's
payload into the canonical shape, then calls the same downstream logic.
See the existing `ghl_transcript_ready` function as a template.

---

## Appendix B: Adapting to a different transcript source

If your CRM only provides audio, not text, add a transcription step.

**Recommended: Deepgram** (~$0.004/min, excellent speaker diarization)

1. Add `deepgram-sdk` to `requirements.txt`
2. Create `app/services/transcription.py` with a `transcribe_url()` function
3. Add a step that runs transcription before the `score_call` task (e.g.
   a new Celery task fired from the webhook when no transcript is present)
4. Add `DEEPGRAM_API_KEY` to config and `.env`

Total work: ~30-60 minutes.

**Alternative:** OpenAI Whisper API (~$0.006/min, no native diarization).

---

## Appendix C: Replacing Slack with another channel

The Slack notifier is isolated in:
- `app/services/slack_client.py` — API client
- `app/core/slack_blocks.py`, `report_blocks.py`, `coaching_blocks.py`, `marketing_blocks.py` — formatters

To replace with Discord, Teams, or email:
1. Create a new notifier module with the same `post_message()` signature
2. Create formatters in your destination's native format
3. Update imports in `app/workers/tasks.py`

---

## Appendix D: Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/health/ready` → `supabase: fail` | Wrong key/URL or old supabase-py | Verify `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` |
| `/health/ready` → `redis: fail` | Redis container not running | `docker compose ps`, restart redis |
| Webhook returns `{"detail":"Invalid signature"}` | `APP_ENV=production` but GHL doesn't HMAC-sign | Set `APP_ENV=development` |
| Webhook returns 422 | Payload validation failure | Check API logs for received keys |
| Scorecard doesn't appear in Slack | Bot not invited to channel | `/invite @bot-name` in the channel |
| `channel_not_found` error | Channel name wrong in `.env` | No `#` prefix: `sales-scorecards` not `#sales-scorecards` |
| Weekly report shows "no calls" | Calls exist but `called_at` is NULL or in current week | Views look at *previous* completed week (Mon-Sun) |
| Worker restart loop | Config error | `docker compose logs worker` — read the first error |
| 502 from Caddy | Backend container down or not on `web` network | `docker network inspect web` |
| Cert issuance fails | DNS not propagated or port 80 blocked | `dig api.<domain>` and `ufw status` |
