# Client Onboarding — Adding a New Tenant to the Same VPS

> **What this is:** a step-by-step checklist for spinning up a *new client*
> on the same VPS that already runs `salesagent` (or any prior client),
> using path-based Caddy routing so each client gets their own
> `https://api.<DOMAIN>/<client-slug>/*` URL.
>
> **Two routing models exist for this project.** This file documents the
> **shared host + path prefix** model (Model 2) — every client lives under
> the same `api.<DOMAIN>` hostname behind a `/<slug>/` prefix.
>
> If the new client should instead get **their own dedicated hostname**
> (e.g. `analyzer.acme.com` with no path prefix), follow
> [`NEW_VPS_ONBOARDING.md`](./NEW_VPS_ONBOARDING.md) instead — it walks
> through the per-client hostname model (Model 1). The `infra/caddy/Caddyfile`
> ships templates for both, and you can mix models on the same host.
>
> **Companion docs:**
> - [`NEW_VPS_ONBOARDING.md`](./NEW_VPS_ONBOARDING.md) — brand-new VPS + brand-new Supabase walkthrough
> - [`INSTALL.md`](./INSTALL.md) — first-time deployment of the system itself
> - [`STATUS.md`](./STATUS.md) — current build state
> - [`CLAUDE.md`](./CLAUDE.md) — project conventions
> - [`infra/caddy/README.md`](./infra/caddy/README.md) — Caddy host setup
>
> Read NEW_VPS_ONBOARDING first if the host doesn't yet exist. Read this
> file when you're adding another client to a VPS that already runs Caddy
> + at least one client.

---

## Architecture recap

Each client is a **separate, isolated stack** on the same host:

- Their own Supabase project (full data isolation)
- Their own Slack bot + channels
- Their own `.env` file
- Their own Docker compose project under `/srv/<client-slug>/`
- One shared Caddy reverse proxy fronts everyone, routing
  `https://api.<DOMAIN>/<client-slug>/*` to that client's API container

The shared external `web` Docker network is how Caddy reaches each
client's API container by name (`<slug>_api:8000`).

This is intentionally NOT multi-tenant inside one app — running fully
isolated stacks is faster to ship, easier to debug, and easier to bill.
Move to true multi-tenancy only after ~3+ clients prove the model.

---

## Pre-flight: information you need from / about the client

- [ ] Their Slack workspace + admin access (or shared workspace + new channels)
- [ ] Their GHL workspace + Private Integration token + Location ID
- [ ] A unique **slug** for the client (lowercase, no spaces) — used in the URL,
      directory name, and container names. Examples: `colt`, `acme-dental`, `xyz`.
      **In this doc we use `colt` as the placeholder — replace it everywhere.**
- [ ] Decide: separate Anthropic API key (billed to client)
      **or** your shared key (you bill them)

---

## Step 1 — Provision their Supabase project

1. Log into [supabase.com](https://supabase.com), create a new project (free tier
   handles thousands of calls per month).
2. Copy from **Settings → API**:
   - **Project URL** → goes into `SUPABASE_URL`
   - **`service_role` secret** → goes into `SUPABASE_SERVICE_KEY`
3. In **SQL Editor**, run all migrations in order. Paste each file's contents,
   run, repeat — takes ~2 minutes total:

   ```
   001_initial.sql                    -- enums, tables, indexes, triggers
   002_views.sql                      -- 30-day rolling + objection views
   003_weekly_views.sql               -- weekly report views
   004_coaching_marketing_views.sql   -- coaching + marketing intel views
   005_ai_outcome.sql                 -- transcript-based outcome detection
   006_enable_rls.sql                 -- RLS + view security_invoker
   ```

4. Verify Tables tab shows `reps`, `calls`, `call_scores`, `coaching_moments`,
   `call_objections`, `scoring_framework`, `rep_kpi_snapshots` — all with the
   RLS-enabled lock icon.

---

## Step 2 — Create their Slack bot

1. In **their** Slack workspace, go to [api.slack.com/apps](https://api.slack.com/apps)
   → **Create New App** → From scratch. Name it something like
   `<Client> Sales Coach`.
2. **OAuth & Permissions** → add **Bot Token Scopes**:
   - `chat:write`
   - `channels:read`
3. **Install to Workspace** → copy the **Bot User OAuth Token**
   (starts with `xoxb-...`) → goes into `SLACK_BOT_TOKEN`.
4. In Slack, create the channels (or use existing ones):
   - `#sales-scorecards` (per-call notifications)
   - `#sales-reports` (weekly reports)
5. Invite the bot to both channels: `/invite @<BotName>`.

---

## Step 3 — Stand up the app on the VPS

```bash
ssh root@2.24.198.69

# 3a. Clone the repo into /srv/<slug>/
cd /srv
git clone git@github.com:KhaledGGL/salesagent.git colt
cd colt

# 3b. Rename containers so they don't collide with the existing client.
# (docker-compose.yml hard-codes container_name: sales_api, sales_worker, etc.
# Two stacks using the same container names will fail to start.)
sed -i 's/sales_api/colt_api/g; s/sales_worker/colt_worker/g; s/sales_beat/colt_beat/g; s/sales_redis/colt_redis/g; s/sales_flower/colt_flower/g' docker-compose.yml

# 3c. Free the host ports — port 8000/6379/5555 are already taken by client #1.
# Caddy reaches each client's API through the `web` docker network by container
# name, so removing the host port bindings is harmless. (You can SSH-tunnel if
# you ever need direct host access for debugging.)
#
# Delete the entire `ports:` block (key + comments + binding line) per service.
# A range delete (`addr1,addr2 d`) is required — deleting only the binding line
# leaves `ports:` dangling above an empty list, which Compose rejects with
# `services.<svc>.ports must be a array`.
sed -i '/^    ports:$/,/127\.0\.0\.1:8000:8000/d' docker-compose.yml
sed -i '/^    ports:$/,/127\.0\.0\.1:6379:6379/d' docker-compose.yml
sed -i '/^    ports:$/,/127\.0\.0\.1:5555:5555/d' docker-compose.yml

# 3d. Create their .env from the template
cp .env.example .env
nano .env
```

Fill in `.env`:

```bash
APP_ENV=development                # GHL doesn't HMAC-sign webhooks — see note below
SECRET_KEY=<openssl rand -hex 32>
WEBHOOK_SECRET=<openssl rand -hex 32>

SUPABASE_URL=https://<their-project>.supabase.co
SUPABASE_SERVICE_KEY=sb_secret_...

REDIS_URL=redis://redis:6379/0     # internal docker hostname, leave as-is

# GHL API credentials are no longer required — the inline-transcript
# webhook + UTM merge tags carries everything the app needs. Leave
# blank unless you're re-introducing a feature that reaches into GHL.
# GHL_API_KEY=
# GHL_LOCATION_ID=

ANTHROPIC_API_KEY=sk-ant-...        # shared or client-specific

SLACK_BOT_TOKEN=xoxb-<their-bot-token>
SLACK_SCORECARD_CHANNEL=sales-scorecards
SLACK_REPORTS_CHANNEL=sales-reports
SLACK_MARKETING_CHANNEL=sales-reports

# Tailor for the client's offer — feeds Claude's scoring + reports
BUSINESS_CONTEXT="<one-paragraph description of what they sell, to whom, price points, common objections>"

WEEKLY_REPORT_DAY=monday
WEEKLY_REPORT_HOUR=8

# CRITICAL: must match the Caddy path prefix exactly. Without it, the
# UI loads but every link/form/pagination breaks (browser strips the
# prefix). Use a leading slash, no trailing slash.
URL_PREFIX=/colt

SENTRY_DSN=                         # leave blank unless you want errors in Sentry
```

**`APP_ENV=development` note:** GHL workflow webhooks don't natively
HMAC-sign payloads. The webhook URL is private and unguessable, which is
acceptable security for the use case. If you ever migrate to a CRM that
*does* sign, flip this to `production`.

```bash
# 3e. Build and start
docker compose up -d --build

# 3f. Confirm all 5 services are up
docker compose ps           # api, worker, beat, redis, flower → "Up"
docker compose logs -f api  # watch for clean startup, Ctrl+C when happy
```

---

## Step 4 — Wire up Caddy routing

```bash
nano /srv/caddy/Caddyfile
```

Inside the `api.{$DOMAIN} { ... }` block, add a new `handle_path` block
**before** the default `handle { respond ... }`. The UI gets its own
sub-block with HTTP basicauth so only the leadership users (CEO, Sales
Manager, Client Manager) can access the dashboard:

```caddy
# ── <Client Display Name> ────────────────────────────────────────────
handle_path /colt/* {
    # Management UI — basicauth-gated for the 3 leadership users.
    # Generate the password hash with:
    #   docker compose exec caddy caddy hash-password
    # Paste the resulting "$2a$..." string after the username below.
    @colt_ui path /ui /ui/*
    handle @colt_ui {
        basicauth {
            colt $2a$14$REPLACE_WITH_CADDY_HASH_PASSWORD_OUTPUT
        }
        reverse_proxy colt_api:8000 {
            header_up X-Real-IP {remote_host}
        }
    }
    # Webhooks + health endpoints — no auth (webhook URL is the secret)
    reverse_proxy colt_api:8000 {
        header_up X-Real-IP {remote_host}
    }
}
```

**Generating the basicauth password hash:**

```bash
cd /srv/caddy
docker compose exec caddy caddy hash-password
# Type a password when prompted (use a password manager — share with the 3 users)
# Copy the entire $2a$... string into the basicauth line above
```

The username (`colt` in the example) can be anything — all three leadership
users share the same credentials. If you ever need per-user accounts, you'd
swap to Supabase Auth, but for read-only management dashboards shared
basicauth is the right tradeoff.

Reload Caddy so it picks up the new route:

```bash
cd /srv/caddy
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
# If reload misbehaves, fall back to a full restart:
docker compose restart caddy
```

Sanity check from outside the VPS:

```bash
# Public endpoints (webhooks + health) — should return 200 without auth
curl -sI https://api.gogrowlabs.com/colt/health/ready
# Expect: HTTP/2 200

# UI — should return 401 without credentials, 200 with them
curl -sI https://api.gogrowlabs.com/colt/ui/
# Expect: HTTP/2 401

curl -sI -u colt:THE_PASSWORD https://api.gogrowlabs.com/colt/ui/
# Expect: HTTP/2 200
```

Once verified, the management dashboard URL to share with the client's
leadership team is:

```
https://api.gogrowlabs.com/colt/ui/
```

---

## Step 5 — Connect their GHL workflow

In **their** GHL workspace:

1. Automations → Workflows → create or edit a workflow
2. Trigger: **Call → Transcript Generated** (the inline-transcript trigger)
3. Action: **Webhook**
   - **Method:** `POST`
   - **URL:** `https://api.gogrowlabs.com/colt/webhooks/ghl/transcript-ready`
   - **Headers:** `Content-Type: application/json`
   - **Body** (use GHL's merge tag picker):

     ```json
     {
       "call_sid": "{{transcript_generated.call_sid}}",
       "call_user_id": "{{transcript_generated.call_user_id}}",
       "call_user_name": "{{user.name}}",
       "call_transcript": "{{transcript_generated.call_transcript}}",
       "call_status": "{{transcript_generated.call_status}}",
       "call_duration": "{{transcript_generated.call_duration}}",
       "contact_id": "{{contact.id}}",
       "contact_name": "{{contact.name}}",
       "contact_email": "{{contact.email}}",
       "contact_phone": "{{contact.phone}}",

       "utm_source":   "{{contact.attributionSource.utmSource}}",
       "utm_medium":   "{{contact.attributionSource.utmMedium}}",
       "utm_campaign": "{{contact.attributionSource.utmCampaign}}",
       "utm_content":  "{{contact.attributionSource.utmContent}}",
       "utm_term":     "{{contact.attributionSource.utmTerm}}"
     }
     ```

   (The exact merge tag names vary slightly across GHL versions — use the
   workflow editor's tag picker rather than typing them by hand. The UTM
   tags live on `contact.attributionSource.*` on most current GHL builds.)

   **About attribution:** these UTM fields drive the entire marketing-loop
   view of the dashboard. Make sure ad campaigns are passing UTMs on the
   landing-page URL so GHL captures them on the contact. Without UTMs the
   call still gets scored cleanly — `lead_source` just stays NULL and the
   call shows up with "—" as its source.

4. Save and publish the workflow.

---

## Step 6 — End-to-end smoke test

Send a synthetic webhook directly to the new endpoint:

```bash
curl -X POST https://api.gogrowlabs.com/colt/webhooks/ghl/transcript-ready \
  -H "Content-Type: application/json" \
  -d '{
    "call_sid": "smoke-test-001",
    "call_user_id": "test-rep",
    "call_user_name": "Test Rep",
    "call_transcript": "Rep: Hi, this is a test call to verify the pipeline end-to-end. We will discuss your back pain. Prospect: Yes I want to buy. Please charge my card and send the program details.",
    "call_status": "completed",
    "contact_id": "test-contact-001",
    "contact_name": "Test Prospect",
    "call_duration": 60
  }'
# Expect: {"status":"accepted","call_id":"<uuid>"}
```

Within ~30 seconds you should see a scorecard in **their** Slack
`#sales-scorecards`. The outcome should classify as `sold` with high
confidence (the transcript explicitly says "charge my card").

Once that works, have them place a real call through GHL to confirm
the full chain end-to-end.

---

## Going forward — code update workflow per client

When you push improvements to `master` on GitHub:

```bash
ssh root@2.24.198.69

# Update each client directory
for slug in salesagent colt; do
  cd /srv/$slug
  git stash                              # set aside the per-client sed edits
  git pull origin master
  git stash pop                          # re-apply the sed edits
  docker compose up -d --build
done
```

The `git stash` dance is needed because Step 3b/3c modified
`docker-compose.yml` in place (sed). On a fresh `git pull` those edits
appear as uncommitted local changes that conflict with upstream changes
to the same file.

**Cleaner long-term option:** refactor `docker-compose.yml` to read
`${COMPOSE_PROJECT_NAME}` from `.env` for container names instead of
hard-coding `sales_*`. Then each client's `.env` sets
`COMPOSE_PROJECT_NAME=colt` and Step 3b disappears entirely. Worth doing
once you've onboarded 2–3 clients and the pattern is proven.

---

## Per-client billing & cost notes

Approximate monthly cost per client (assuming ~200 calls/month):

| Item | Cost |
|---|---|
| Supabase project | $0 (free tier, ~500 MB / 50 K monthly reads) |
| Anthropic API (Sonnet 4.6, 3 LLM calls per scored call + 2 weekly) | ~$15–25 |
| Slack | $0 |
| VPS slice (shared) | $0 marginal — same host as other clients |
| **Per-client COGS** | **~$15–25/mo** |

Charge accordingly. The unit economics scale linearly until the VPS
needs upgrading (probably ~5–10 clients on a Hostinger 4 GB box).

---

## Decommissioning a client

If a client churns:

```bash
ssh root@2.24.198.69

# Stop and remove their stack
cd /srv/colt
docker compose down -v          # -v also removes their Redis volume

# Remove their Caddy route
nano /srv/caddy/Caddyfile       # delete their handle_path block
cd /srv/caddy && docker compose exec caddy caddy reload \
    --config /etc/caddy/Caddyfile --adapter caddyfile

# Archive their directory and remove
cd /srv
tar czf /root/archive-colt-$(date +%F).tar.gz colt/
rm -rf colt/

# Optional: pause their Supabase project from the dashboard
# (data is preserved; can be resumed any time)
```

Their data stays in Supabase by default (so you can resume billing or
hand off the project). Delete the Supabase project itself only if they
explicitly request it.
