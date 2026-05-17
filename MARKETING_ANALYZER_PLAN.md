# Marketing Analyzer — Design & Build Plan

> **Milestone 2** of the GoGrowLabs RevOps product suite.
> **Milestone 1** (Sales Call Analyzer / salesagent) is live and deployed
> on two VPSes — see `STATUS.md` for its state.
>
> Last updated: 2026-05-17
> Status: design phase complete; build not yet started.

---

## 1. Product scope

A standalone marketing analytics product that covers the *upstream* funnel
end-to-end:

```
Ad platforms ──► Audiences ──► Creatives ──► Landing/Funnel ──► Optin/Application ──► Booking
   (spend)        (segments)    (variants)    (page metrics)     (form submits)        (calendar)
```

Optionally **linked to the Sales Call Analyzer** for full closed-loop sales
and marketing analysis: ad spend → call quality → close rate, plus
cross-domain coaching and insights.

**Critical product constraint:** funnel topology varies per client. Some
have application gates, some direct bookings, some webinar funnels, some
quiz-to-nurture flows, some DM-based. The product must bend to whatever
shape the client runs — pipeline definition is configuration, not code.

**Sellable as a separate product** from the Sales Call Analyzer. License
model is per-client VPS with transferable ownership; sales-only,
marketing-only, and combined bundles all install independently.

---

## 2. Locked architectural decisions

### A. Funnel as a configurable stage graph (custom shape, curated vocabulary)

A client's funnel is a **directed graph of stages**, built in a visual
UI per client. Each stage has both a user-chosen label and a curated
semantic category — the graph shape is theirs; the vocabulary is ours.

```
Pipeline (custom DAG, built in UI)
  └── Stage (custom)
        ├── name:       "Strategy Session Apply"   ← user-typed, anything
        ├── category:   ApplicationSubmit          ← from curated enum
        ├── parents:    [LandingView stage_id]     ← edges drawn in UI
        ├── identity_keys: [email, phone]
        ├── integrations:
        │     ├── source: GHL form "apply_form_v3"
        │     └── source: Typeform "form_xyz"
        └── lookback_to_parent: 14 days            ← per-edge attribution window
```

**Why both layers:** purely free-form stages break the AI layer
(Claude can't reason semantically about an "OptinSubmit" if it doesn't
know what one is), break integrations (Meta lead-form events have
nowhere to auto-route), and break cross-client benchmarks. The curated
category enum stays the semantic anchor; the custom name + edges give
clients all the shape flexibility they need.

**Curated category enum (v1):**
- `Impression` — ad shown
- `AdClick` — ad clicked
- `LandingView` — landing page hit
- `EngagementEvent` — page interaction (video play, quiz step, etc.)
- `OptinSubmit` — basic email/phone capture
- `ApplicationSubmit` — long-form qualifying submit
- `Qualified` — explicit qualification step (manual or rule-based)
- `BookingCreated` — calendar booking made
- `BookingShowed` / `NoShow` — attendance outcomes
- `CallScored` — comes from salesagent (closed-loop only)
- `Closed` / `Lost` — terminal outcomes
- `Custom` — escape hatch for genuine edge cases (no AI / benchmarks)

**Templates shipped in v1:** 3 starting templates covering ~80% of the
target segment: *Application funnel*, *Direct-booking funnel*,
*Webinar funnel*. *Quiz/nurture* and *DM/manual* added in v2.

**Pipeline versioning:** events attach to the version of the pipeline
they were ingested under. v1 ships single-version-per-client; full
versioning UI deferred to v2.

### B. Identity stitching: deterministic + click-ID + manual escape hatch

Every stage event arrives with a different identity key (Meta click_id,
landing cookie, optin email, booking phone, call_sid). They must fuse
into one `Lead` record or every join downstream is garbage.

**Matching tiers:**

| Level | Method | Coverage | Ships in |
|---|---|---|---|
| 1. Deterministic exact | `email==email`, `phone==phone`, `click_id==click_id` | ~70% | v1 |
| 2. Deterministic normalized | lowercased email, E.164 phone, stripped whitespace | ~85% | v1 |
| 3. Click-ID stitching | Carry `fbclid`/`gclid` from URL → landing cookie → form submit | ~92% | **v2** |
| 4. Fuzzy match | Levenshtein on email, name+phone heuristics | ~95% | **never** |
| 5. Probabilistic | IP / device fingerprint | ~97% | **never** |

**Rationale for stopping at Level 3:** SMB high-ticket coaching segment
has hundreds of leads/week, not millions. Levels 1-3 give >90% coverage
with zero false-positive risk. Fuzzy introduces a merge-error tax
(support tickets, manual unmerges). Probabilistic introduces GDPR/CCPA
exposure. Remaining ~5-8% gap handled by a manual lead-attach UI.

**Data model:**
```
Lead
  └── has many LeadIdentity rows
        ├── type:  email | phone | click_id | session_id | crm_contact_id | call_sid
        ├── value: normalized
        └── source: which stage event first attached it
```

**Resolver logic** runs on every inbound event: normalize identities,
look up in `LeadIdentity`, then create / attach / merge. Cross-Lead
identity overlap (e.g. optin event carries both a known click_id and a
known email pointing to different prior Leads) triggers a **merge** —
one Lead wins, others become aliases, merge logged for audit.

**Manual escape hatch** (v1): unattributed-events feed + lead-attach
action + merge history + manual unmerge — server-rendered admin UI
similar to salesagent's `/ui/*` shape.

**Known limitations of stopping at Level 3:**
- Cross-device pre-optin journeys are lost (same person clicks Meta on
  phone, fills optin on desktop — no overlap until email/phone is given)
- Iframe/redirect ad URLs that strip query params drop click_id
- Both mitigated by client education + the manual merge UI

### C. Per-VPS per-client hosting (transferable license)

Each client's VPS hosts whatever products they purchased. **Not a
shared multi-tenant SaaS.** Rationale: business model is per-client
license/ownership transfer — clients pay for and own their stack.
Shared infrastructure would prevent transfer.

```
Per client VPS (e.g. Calivus's box):

  /srv/<client_slug>/                  ← single unified docker stack per client
     docker-compose.yml                  (selected per purchased bundle)
     ├── app          (FastAPI: /sales/* and/or /marketing/*)
     ├── worker       (Celery: sales queue + marketing queue)
     ├── beat         (scheduled: weekly reports + ad API pulls)
     ├── redis
     └── flower

  /srv/caddy/                          ← existing reverse proxy
     Caddyfile        (routes <client>.gogrowlabs.com → app)

Single domain per client:
  https://<client>.gogrowlabs.com/              (login / overview)
                            /sales/*           (salesagent UI, if installed)
                            /marketing/*       (marketing UI, if installed)
                            /webhooks/sales/*       (GHL ingest)
                            /webhooks/marketing/*   (forms, calendars, etc.)
```

**Single Supabase project per client** regardless of products installed.
Schema isolation by table prefix (`sales_*`, `marketing_*`) so loop-closing
SQL views work natively when both products are installed.

**Two new operational problems** introduced by per-VPS architecture
(both have explicit solutions below):

### D. Modular packaging (sales / marketing / combined bundles)

Repo structure:

```
gogrowlabs/                        ← one monorepo
  ├── core/                        ← shared: auth, Caddy config, UI shell, db, observability
  ├── sales/                       ← salesagent product
  │   ├── Dockerfile               ← builds gogrowlabs/sales:vX.Y.Z
  │   ├── pyproject.toml
  │   └── migrations/              ← sales-only schema
  ├── marketing/                   ← marketing analyzer product
  │   ├── Dockerfile               ← builds gogrowlabs/marketing:vX.Y.Z
  │   ├── pyproject.toml
  │   └── migrations/              ← marketing-only schema
  └── deploy/
      ├── compose.sales-only.yml
      ├── compose.marketing-only.yml
      └── compose.combined.yml     ← both + loop-closing view enabled
```

**Key property:** each product's Dockerfile copies only `core/` + its
own product directory. A sales-only client's VPS has zero marketing
code on disk. License boundary is physical, defensible.

**Per-bundle deploy footprint:**

| Bundle | Containers | Supabase schemas | Loop-closing |
|---|---|---|---|
| sales-only | caddy, sales-app, sales-worker, sales-beat, redis | `sales_*` only | n/a |
| marketing-only | caddy, marketing-app, marketing-worker, marketing-beat, redis | `marketing_*` only | n/a |
| combined | caddy, sales-app, sales-worker, marketing-app, marketing-worker, beat, redis | both | enabled via SQL view |

In **combined** mode: shared Redis (separate queue names per product),
shared Caddy (routes `/sales/*` and `/marketing/*` to the right
container), shared Supabase project. Loop-closing runs as a Celery task
in marketing-worker, reading `sales_calls` via shared DB and attaching
`CallScored` stage events to matching leads (no HTTP between containers).

**Cross-client benchmarks** (since per-VPS prevents shared queries):
- **Tier 0 — Curated/public benchmarks (v1):** hand-curated industry
  numbers baked into AI prompt context.
- **Tier 1 — Opt-in anonymized aggregate uploader (v2):** each VPS
  optionally POSTs weekly anonymized stats to a central
  `benchmarks.gogrowlabs.com` service. Returns peer percentiles.
- **Tier 2 — Federated query:** not building.

**Fleet updates across N VPSes:**
- Build and push tagged images to **GHCR private registry** (free)
- Each VPS runs **Watchtower** pulling the `:stable` tag on a nightly cron
- Risky changes go through `:beta` on a canary VPS, then promote
- Breaking changes (DB migrations) run via Ansible playbook or bash loop

**Auth in combined mode:** single login per VPS (basicauth via Caddy
matches today's salesagent pattern, or Supabase Auth scoped to the
VPS's client users). Both products appear in shared nav.

### E. Pricing & packaging (deferred)

Three-component pricing structure to be designed:
- Sales-only tier ($/mo)
- Marketing-only tier ($/mo)
- Combined tier (Sales + Marketing + closed-loop value-add surcharge)

Plus considerations: setup fee covering VPS provisioning + onboarding,
license-transfer mechanics, support/maintenance SLAs.

**Status: TBD.** Not blocking build start. Revisit before first paid
marketing-only or combined sale.

---

## 3. Build plan

### Phase 0 — Repo refactor (1-2 days, blocking)

Move existing salesagent into the new modular structure. No behavior
change for live VPSes; Caddy paths and webhook URLs stay identical.

- Move `app/` → `sales/app/`
- Move `tests/` → `sales/tests/`
- Move `001_initial.sql`, `002_views.sql`, `003_weekly_views.sql`, etc.
  → `sales/migrations/`
- Extract shared bits (DB client singleton, auth helpers, observability,
  Caddy config, UI shell) → `core/`
- Bootstrap empty `marketing/` skeleton
- Write `deploy/compose.sales-only.yml` (≈ current `docker-compose.yml`)
- Set up GHCR private registry + Watchtower on existing VPSes
- Update onboarding docs + `NEW_VPS_ONBOARDING.md`

Ship as a single PR; all 259 existing tests must still pass.

### Phase 1 — Marketing MVP (~5 weeks)

**Design partner: Calivus** — already paying, funnel context known,
salesagent already installed (so combined bundle is "just add the
marketing container").

| Week | Focus |
|---|---|
| 1 | Schema (leads, lead_identities, stages, stage_events, pipelines, integrations) + identity resolver (deterministic exact + normalized) + inbound webhooks (form-submit / booking-created / generic) |
| 2 | Visual pipeline builder (Drawflow) + 3 templates + per-stage config sidebar + validation (no cycles, terminal reachable, etc.) |
| 3 | Meta Ads ingest (Celery beat, 6h cadence) — spend, campaigns, audiences, creative metadata |
| 4 | Closed-loop SQL view (combined bundle) + dashboard pages (funnel overview / campaigns / cost-per-outcome / leads feed) + Slack weekly marketing report (AI-synthesized) |
| 5 | Manual merge / lead-attach UI + polish + Calivus deployment |

**In v1:**
- Schema + migrations
- Identity resolver — deterministic exact + normalized only
- Visual pipeline builder (Drawflow library — vanilla JS, no toolchain)
- 3 templates (Application / Direct-booking / Webinar)
- Inbound webhooks
- Meta Ads ingest (full — spend, campaigns, audiences, creative metadata)
- Dashboard pages
- Closed-loop SQL view (combined mode only)
- Weekly Slack marketing report
- Manual merge / lead-attach UI
- Curated industry benchmarks in AI prompts (Tier 0)

**Explicitly OUT of v1 (deferred to v2):**
- DAG canvas upgrade to React Flow (Drawflow is enough for v1)
- Click-ID stitching (`fbclid`/`gclid` through landing → form)
- Creative AI analysis (Claude reads ad copy + creatives)
- Pipeline versioning UI
- Google Ads / TikTok / LinkedIn ingest
- Test-mode / "fire fake event at stage" button
- Multi-touch attribution toggle (last-touch only in v1)
- Self-serve onboarding (Calivus configured by hand)
- Anonymized cross-client benchmarks (Tier 1)
- Pipeline builder undo/redo, multi-select, auto-layout

**Explicitly OUT forever:**
- Fuzzy matching (Level 4)
- Probabilistic identity stitching (Level 5)

### Phase 2 — v2 (2-3 weeks after v1 ships)

The polish that turns v1's "works for Calivus" into "I can sell this."

- Visual DAG canvas upgrade to React Flow (richer UX, undo/redo, polish)
- Click-ID stitching: Meta `fbclid` through GHL landing pages, then
  optional JS snippet for custom landing pages
- Google Ads ingest
- Creative AI analysis: Claude reads ad copy + creative metadata,
  explains winners vs losers, generates creative briefs
- Pipeline versioning
- Test mode / fire-fake-event

### Phase 3 — v3 (when sales velocity demands it)

- Anonymized benchmarks uploader (Tier 1, opt-in)
- Self-serve onboarding for technical clients
- TikTok / LinkedIn ads
- Multi-touch attribution model selection
- Advanced segmentation / audience analytics

---

## 4. Stack additions (new in milestone 2)

| Component | Purpose | Notes |
|---|---|---|
| **Drawflow** | Visual pipeline builder canvas (v1) | Vanilla JS, drop-in script tag, ~30KB |
| **React Flow** (`@xyflow/react`) | DAG canvas upgrade (v2) | Requires Vite + React island; defer until v2 |
| **Meta Marketing API SDK** | Ad spend / campaign / creative ingest | OAuth via Meta Business System User |
| **Watchtower** | Auto-pull Docker images on VPSes | Standard tool, ~5MB |
| **GHCR (private)** | Docker image registry | Free for private repos |

Anthropic Claude, Supabase, Celery, Redis, FastAPI, Caddy, Slack all
already in stack from Milestone 1.

---

## 5. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Combined-bundle regression breaks both products at once | CI runs integration test against combined bundle on every PR; staging VPS validates before promoting to `:stable` |
| Drift between sales and marketing versions in combined mode | Compatibility matrix per release; pin specific image tags in `compose.combined.yml` |
| Migration ordering in combined mode | Each product's migrations namespaced to its own schema/prefix; no collision possible |
| Fleet update breaks a client's VPS at 3am | Canary on `:beta` tag; `:stable` only promoted after canary clears; SSH access remains for hotfix |
| Ad API token rotation across N VPSes | Documented re-auth flow + admin endpoint in each VPS for one-command token refresh |
| Bad merge in identity resolver | Merge history with unmerge; merges logged with joining identity |
| Calivus's funnel doesn't fit the abstraction | Form-based + Drawflow validates abstraction in week 2 before Meta ingest is built; cheap to discover and adjust |
| Meta API rate limits during ingest | 6h polling cadence + exponential backoff + per-account token bucket |

---

## 6. Open questions for the next session

- **Fork E — Pricing.** Three-component tiering (sales-only / marketing-only / combined) with closed-loop as value-add surcharge. Setup fee, license-transfer mechanics, support SLA all TBD.
- **Calivus engagement framing.** Free upgrade to combined? Beta-partner discount? Confirms-or-revises by demo at end of Phase 1.
- **Naming.** "Marketing Analyzer" is the working name. Final brand TBD.
- **GHCR vs Docker Hub.** Both work; GHCR has tighter GitHub integration. Default GHCR unless reason to switch.

---

## 7. How to resume

1. Read this doc first
2. Read `STATUS.md` for Milestone 1 state
3. Read `CLAUDE.md` for repo conventions
4. Start with **Phase 0 — Repo refactor**. Ship as one PR. Verify all
   259 existing tests pass + both production VPSes still serve traffic
   correctly after `:stable` tag is pushed.
5. Then start **Phase 1 Week 1** — schema design + identity resolver +
   inbound webhooks. Tests-first as with Milestone 1.

When in a new Claude Code session, just say:
> "Pick up where we left off on the Marketing Analyzer — check
> `MARKETING_ANALYZER_PLAN.md`."
