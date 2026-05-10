# New VPS + New Supabase — End-to-End Client Onboarding

> **What this is:** the linear walkthrough for spinning up a brand-new
> client on a brand-new VPS with a brand-new Supabase project. Use this
> when neither the host nor the database exists yet.
>
> **Companion docs:**
> - [`INSTALL.md`](./INSTALL.md) — reference install (more verbose,
>   includes troubleshooting appendices)
> - [`ONBOARDING.md`](./ONBOARDING.md) — adding *another* tenant to a VPS
>   that already runs Caddy + at least one client
> - [`STATUS.md`](./STATUS.md) — current build state
> - [`CLAUDE.md`](./CLAUDE.md) — project conventions
> - [`infra/caddy/README.md`](./infra/caddy/README.md) — Caddy host setup
>
> **Hosting model used in this doc: per-client hostname.** Each client
> brings their own domain (or any subdomain of yours). Caddy obtains a
> separate Let's Encrypt cert per host. No URL prefix, no shared
> `api.<your-domain>` wrapper. Cleaner URLs and full per-client isolation.
>
> Replace these placeholders everywhere they appear:
> - `<slug>` — internal identifier (`acme`, `colt`); used for container
>   names, directory, never visible in URLs
> - `<CLIENT_HOSTNAME>` — the public hostname the client will use
>   (`analyzer.client1.com`, `sales.client2.io`, `app.<your-domain>`, …)
> - `<VPS_IP>` — the VPS public IP

---

## 0. Pre-flight — gather BEFORE you start

- [ ] **VPS** — Ubuntu 22.04+, 2 GB RAM min, root SSH access
- [ ] **Hostname** — any FQDN the client (or you) controls. Apex
      (`acme.com`) and subdomain (`analyzer.acme.com`) both work; subdomain
      is recommended so the apex stays free for their marketing site
- [ ] **Slug** — lowercase, no spaces (`acme`, `colt`)
- [ ] **Supabase** account — https://supabase.com/dashboard
- [ ] **Anthropic Console** account + $50/mo spending cap set FIRST — https://console.anthropic.com
- [ ] **Slack admin** in the client's workspace
- [ ] **Client's GHL workspace** access (to wire the workflow webhook)
- [ ] One paragraph from the client describing **what they sell, to whom, price points, common objections** (drives `BUSINESS_CONTEXT`)

---

## 1. DNS first (so cert issuance has time to propagate)

At whichever registrar holds `<CLIENT_HOSTNAME>`, add:

| Type | Name | Value | TTL |
|---|---|---|---|
| A | `<subdomain or @>` | `<VPS_IP>` | default |

Examples:
- `analyzer.acme.com` → A record `analyzer` at `acme.com`'s registrar
- `app.gogrowlabs.com` → A record `app` at `gogrowlabs.com`'s registrar

Verify from your laptop:

```bash
dig <CLIENT_HOSTNAME> +short    # must return <VPS_IP>
```

You can repeat this step per client — each tenant gets its own A record
pointing at the same VPS IP. Caddy picks the right block by `Host` header.

---

## 2. Provision the VPS

```bash
ssh root@<VPS_IP>

apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version

# Shared docker network — Caddy talks to each client API by container name on this net
docker network create web

# Firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

apt install -y git
```

---

## 3. Stand up Caddy (reverse proxy + auto TLS)

```bash
git clone https://github.com/KhaledGGL/salesagent.git /srv/salesagent-template
cp -r /srv/salesagent-template/infra/caddy /srv/caddy

# Per-host blocks declare their hostname literally, so only ACME_EMAIL is
# required. (DOMAIN is only used by the legacy shared-host block, which
# we'll leave commented out for new per-host deployments.)
cat > /srv/caddy/.env << 'EOF'
ACME_EMAIL=you@example.com
DOMAIN=unused.example.com
EOF

cd /srv/caddy
docker compose up -d
docker compose logs -f caddy
# Caddy boots; it won't issue a cert until a client hostname block is added
# (Step 8). Ctrl+C once the container is healthy.
```

---

## 4. Provision the Supabase project

1. https://supabase.com/dashboard → **New Project** → closest region → save the DB password
2. **SQL Editor** → run these in order (paste each file's contents, run, repeat):

   ```
   001_initial.sql
   002_views.sql
   003_weekly_views.sql
   004_coaching_marketing_views.sql
   005_ai_outcome.sql
   006_enable_rls.sql
   007_weekly_reports.sql
   008_simplify_to_inline_only.sql
   ```

3. Verify in **Tables** tab: `reps`, `calls`, `call_scores`,
   `coaching_moments`, `call_objections`, `scoring_framework`,
   `rep_kpi_snapshots` — all with the RLS lock icon.
4. **Settings → API** → copy:
   - **Project URL** → `SUPABASE_URL`
   - **service_role secret** (NOT anon) → `SUPABASE_SERVICE_KEY`

---

## 5. Anthropic key

1. Console → **Settings → Limits** → set monthly cap (~$50 for 500–1000 calls)
2. **API Keys → Create Key** → `ANTHROPIC_API_KEY`

---

## 6. Slack bot (in the client's workspace)

1. https://api.slack.com/apps → **Create New App → From scratch** → name `<Client> Sales Coach`
2. **OAuth & Permissions → Bot Token Scopes**: `chat:write`, `chat:write.public`, `channels:read`
3. **Install to Workspace** → copy **Bot User OAuth Token** (`xoxb-...`) → `SLACK_BOT_TOKEN`
4. Create channels: `#sales-scorecards`, `#sales-reports`
5. **Invite the bot to BOTH channels** (`/invite @<botname>`) — most-skipped step that causes silent failure

---

## 7. Stand up the client stack on the VPS

```bash
ssh root@<VPS_IP>
cd /srv
git clone https://github.com/KhaledGGL/salesagent.git <slug>
cd /srv/<slug>

# Rename containers so they never collide with future tenants on the same host
sed -i 's/sales_api/<slug>_api/g; s/sales_worker/<slug>_worker/g; s/sales_beat/<slug>_beat/g; s/sales_redis/<slug>_redis/g; s/sales_flower/<slug>_flower/g' docker-compose.yml

# Free host ports — Caddy reaches the API over the `web` network by container name.
# Single sed: enters delete mode at each `    ports:` line and exits at that
# block's binding line. The addr2 regex anchors on `      - "127.0.0.1:` so it
# only matches actual binding lines, never prose comments that mention
# `127.0.0.1` (the api block's comments do — that's a real footgun).
sed -i '/^    ports:$/,/^      - "127\.0\.0\.1:/d' docker-compose.yml

cp .env.example .env
nano .env
```

Fill `.env`:

```bash
APP_ENV=development                 # GHL webhooks aren't HMAC-signed
SECRET_KEY=$(openssl rand -hex 32)
WEBHOOK_SECRET=$(openssl rand -hex 32)

SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=sb_secret_...

REDIS_URL=redis://redis:6379/0

ANTHROPIC_API_KEY=sk-ant-...

SLACK_BOT_TOKEN=xoxb-...
SLACK_SCORECARD_CHANNEL=sales-scorecards
SLACK_REPORTS_CHANNEL=sales-reports
SLACK_MARKETING_CHANNEL=sales-reports

BUSINESS_CONTEXT="<one paragraph: what they sell, to whom, price, common objections>"

WEEKLY_REPORT_DAY=monday
WEEKLY_REPORT_HOUR=8

# Per-host model: leave blank. The app serves from `/` and Caddy maps
# `<CLIENT_HOSTNAME>` directly to it. Only set this if you're using the
# legacy shared-host model (api.<DOMAIN>/<slug>/*).
URL_PREFIX=

SENTRY_DSN=
```

Build & start:

```bash
docker compose up -d --build
docker compose ps           # all 5 containers Up
docker compose logs -f api  # confirm clean startup
```

---

## 8. Wire up Caddy routing for this client's hostname

```bash
nano /srv/caddy/Caddyfile
```

Under the **MODEL 1 — Per-client hostname** section, add a new block.
Replace `<CLIENT_HOSTNAME>` and `<slug>` with this client's values:

```caddy
# ── <Client Display Name> — slug=<slug> ─────────────────────
<CLIENT_HOSTNAME> {
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }

    @ui path /ui /ui/*
    handle @ui {
        basicauth {
            <slug> $2a$14$REPLACE_WITH_HASH
        }
        reverse_proxy <slug>_api:8000 {
            header_up X-Real-IP {remote_host}
        }
    }

    reverse_proxy <slug>_api:8000 {
        header_up X-Real-IP {remote_host}
    }
}
```

Generate the basicauth hash and paste it in:

```bash
cd /srv/caddy
docker compose exec caddy caddy hash-password
```

Reload Caddy (it will obtain a fresh Let's Encrypt cert for the new
hostname on first request — give it ~10 seconds):

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose logs -f caddy   # watch for "certificate obtained successfully"
```

Sanity:

```bash
curl -sI https://<CLIENT_HOSTNAME>/health/ready                  # 200
curl -sI https://<CLIENT_HOSTNAME>/ui/                           # 401 without auth
curl -sI -u <slug>:<password> https://<CLIENT_HOSTNAME>/ui/      # 200
```

---

## 9. Smoke-test the pipeline end-to-end

```bash
# Validates Slack + Celery + Postgres + Redis (no Claude call)
docker compose -f /srv/<slug>/docker-compose.yml exec worker python -m app.cli run-weekly-report
# → "No scored calls this week" lands in #sales-reports

# Validates Claude scoring + Slack scorecard
curl -X POST https://<CLIENT_HOSTNAME>/webhooks/ghl/transcript-ready \
  -H "Content-Type: application/json" \
  -d '{
    "call_sid":"smoke-001",
    "call_user_id":"test-rep",
    "call_user_name":"Test Rep",
    "call_transcript":"Rep: Hi, just verifying the pipeline. Prospect: Yes I want to buy, charge my card.",
    "call_status":"completed",
    "contact_id":"test-contact-001",
    "contact_name":"Test Prospect",
    "call_duration":60
  }'
# → {"status":"accepted","call_id":"<uuid>"}
# Within ~30s, scorecard appears in #sales-scorecards classified `sold`
```

If the scorecard arrives, the system is fully operational.

---

## 10. Connect the client's GHL workflow

In **the client's** GHL:

1. **Automation → Workflows → New**
2. **Trigger:** Call → *Transcript Generated*
3. **Action:** Webhook
   - **Method:** `POST`
   - **URL:** `https://<CLIENT_HOSTNAME>/webhooks/ghl/transcript-ready`
   - **Headers:** `Content-Type: application/json`
   - **Body** (use the merge-tag picker — names vary by GHL version):

     ```json
     {
       "call_sid":        "{{transcript_generated.call_sid}}",
       "call_user_id":    "{{transcript_generated.call_user_id}}",
       "call_user_name":  "{{user.name}}",
       "call_transcript": "{{transcript_generated.call_transcript}}",
       "call_status":     "{{transcript_generated.call_status}}",
       "call_duration":   "{{transcript_generated.call_duration}}",
       "contact_id":      "{{contact.id}}",
       "contact_name":    "{{contact.name}}",
       "contact_email":   "{{contact.email}}",
       "contact_phone":   "{{contact.phone}}",
       "utm_source":      "{{contact.attributionSource.utmSource}}",
       "utm_medium":      "{{contact.attributionSource.utmMedium}}",
       "utm_campaign":    "{{contact.attributionSource.utmCampaign}}",
       "utm_content":     "{{contact.attributionSource.utmContent}}",
       "utm_term":        "{{contact.attributionSource.utmTerm}}"
     }
     ```

4. Save & Publish. Have a rep place a real call → confirm scorecard in Slack.

Make sure landing pages pass UTMs so GHL captures them on the contact —
without UTMs, calls still score cleanly but `lead_source` stays NULL and
the call shows up with "—" as its source on the dashboard.

---

## 11. Hand-off

Share with the client:

- Dashboard: `https://<CLIENT_HOSTNAME>/ui/` + basicauth credentials
- Webhook URL (for their records): `https://<CLIENT_HOSTNAME>/webhooks/ghl/transcript-ready`
- Slack channels: `#sales-scorecards`, `#sales-reports`
- Weekly cadence: Mon 8:00 — sales report, coaching lesson, marketing intel

---

## 12. Production hardening (do before real traffic)

- [ ] Anthropic monthly cap set
- [ ] All containers `restart: unless-stopped`
- [ ] Sentry DSN populated (or another alerting channel)
- [ ] Supabase daily backups confirmed (free tier includes them)
- [ ] `.env` not in git, chat, or screenshots
- [ ] Bot invited to **both** Slack channels
- [ ] Flower (`:5555`) firewalled or removed
- [ ] Rotate `SUPABASE_SERVICE_KEY` if it ever appeared in a chat/screenshot

---

## Update workflow going forward

When you push to `master`:

```bash
ssh root@<VPS_IP>
cd /srv/<slug>
git stash                 # preserve the sed edits to docker-compose.yml
git pull origin master
git stash pop
docker compose up -d --build
docker compose restart worker beat   # required after any prompts.py change
```

The `git stash` dance is needed because Step 7 modified
`docker-compose.yml` in place via `sed`. Long-term cleanup: refactor the
compose file to read `${COMPOSE_PROJECT_NAME}` from `.env` for container
names. After 2–3 clients prove the pattern, that change pays for itself.

---

## Adding more clients to the same VPS

Once Caddy is up, every additional tenant is:

1. New A record at the new client's registrar pointing to `<VPS_IP>`
2. New Supabase project + run the migrations
3. New Slack bot
4. New `/srv/<slug>/` directory (Step 7)
5. New host block in `/srv/caddy/Caddyfile` (Step 8) — Caddy reload, fresh
   cert per host
6. Wire their GHL workflow to `https://<their-hostname>/webhooks/...`

No changes to existing tenants. They each have their own hostname, cert,
container set, Supabase project, and Slack bot — full isolation.
