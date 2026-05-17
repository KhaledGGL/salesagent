# Phase 0 — Repo Refactor Plan

> **Purpose:** Reorganize the salesagent monorepo into the modular
> structure (`core/` + `sales/` + `marketing/` + `deploy/`) called for
> by `MARKETING_ANALYZER_PLAN.md`, without changing any runtime
> behavior on the two live VPSes.
>
> **Scope:** Mechanical refactor only. No new features. No new tests
> beyond what's needed to verify the move. All 259 existing tests
> must stay green.
>
> **Estimated effort:** 1-2 focused days. One PR, ~4 commits.
>
> **Status:** Plan locked 2026-05-17, ready to execute.

---

## 1. Current state

```
salesagent/
├── app/                      ← Python package
│   ├── main.py               (FastAPI entrypoint)
│   ├── db.py                 ← SHARED concern (Supabase singleton)
│   ├── logging.py            ← SHARED concern
│   ├── observability.py      ← SHARED concern (Sentry)
│   ├── redis.py              ← SHARED concern
│   ├── cli.py                (sales-specific replay CLI)
│   ├── core/                 (sales-specific: prompts, slack blocks)
│   ├── services/             (sales-specific: claude, slack)
│   ├── ui/                   (sales-specific routes + helpers)
│   ├── templates/            (sales-specific Jinja)
│   ├── webhooks/             (sales-specific: ghl.py)
│   └── workers/              (sales-specific: celery_app, tasks)
├── config.py                 ← SHARED concern (pydantic settings)
├── schemas.py                ← sales-specific pydantic models
├── 001-008.sql               ← sales-specific migrations
├── Dockerfile
├── docker-compose.yml
├── docker-compose.dev.yml
├── tests/                    (259 tests, ~2s runtime)
├── infra/caddy/              ← unrelated reverse proxy, stays put
├── Makefile / pytest.ini / requirements*.txt / .env / .github/
└── docs (CLAUDE/STATUS/INSTALL/ONBOARDING/NEW_VPS_ONBOARDING/MARKETING_ANALYZER_PLAN)
```

**Import surface:** 30 cross-module imports in `app/`, 13 in `tests/`.
Mostly `from app.X`, `from config`, `from schemas`. All mechanically
rewritable via sed.

## 2. Target state

```
salesagent/                   (repo name unchanged for git history)
├── core/                     ← NEW: shared infrastructure
│   ├── __init__.py
│   ├── config.py             (← moved from root config.py)
│   ├── db.py                 (← moved from app/db.py)
│   ├── logging.py            (← moved from app/logging.py)
│   ├── observability.py      (← moved from app/observability.py)
│   └── redis.py              (← moved from app/redis.py)
├── sales/                    ← NEW: Sales Call Analyzer product
│   ├── __init__.py
│   ├── Dockerfile            (← moved + adjusted)
│   ├── app/                  (← moved from app/)
│   │   ├── main.py
│   │   ├── cli.py
│   │   ├── core/
│   │   ├── services/
│   │   ├── ui/
│   │   ├── templates/
│   │   ├── webhooks/
│   │   └── workers/
│   ├── schemas.py            (← moved from root)
│   ├── migrations/           (← 001-008.sql moved here)
│   └── tests/                (← moved from root tests/)
├── marketing/                ← NEW: skeleton for milestone 2
│   ├── __init__.py
│   ├── Dockerfile            (placeholder; references core/ + marketing/)
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py           (FastAPI, hello-world)
│   ├── schemas.py            (empty stub)
│   ├── migrations/           (empty)
│   └── tests/
│       └── conftest.py       (env-var stub only)
├── deploy/                   ← NEW: bundle compose files
│   ├── compose.sales-only.yml      (← rename of docker-compose.yml)
│   ├── compose.marketing-only.yml  (skeleton)
│   ├── compose.combined.yml        (skeleton)
│   └── compose.dev.yml             (← rename of docker-compose.dev.yml)
├── requirements/             ← NEW: split per product
│   ├── shared.txt            (fastapi, uvicorn, pydantic, supabase, redis, sentry, jinja2, httpx)
│   ├── sales.txt             (anthropic, slack-sdk, celery, flower — and `-r shared.txt` header)
│   ├── marketing.txt         (just `-r shared.txt` for now; deps added in Phase 1)
│   └── dev.txt               (test-time tools — pytest, etc. — and `-r sales.txt -r marketing.txt`)
├── pytest.ini                (updated: testpaths = sales/tests marketing/tests)
├── Makefile                  (updated: BUNDLE-aware targets)
├── docker-compose.yml        (thin `include: deploy/compose.sales-only.yml` wrapper for live VPS backward compat)
├── .github/workflows/
│   ├── ci.yml                (updated paths)
│   └── publish-images.yml    (NEW: GHCR image build + push on master)
├── infra/caddy/              (unchanged)
└── docs                      (paths updated where they reference app/ or root files)
```

## 3. Decisions locked

| # | Decision | Rationale |
|---|---|---|
| 1 | GHCR namespace = `ghcr.io/khaledggl/gogrowlabs-sales` and `…/gogrowlabs-marketing` | Uses existing personal GH account `KhaledGGL`; transferable to a `gogrowlabs` org later via GHCR package transfer if needed. No new org to create. |
| 2 | Split requirements into `requirements/shared.txt` + per-product files in Phase 0 | ~30 min cost; avoids a refactor when marketing gets its first dep (Drawflow needs nothing on the Python side, but Meta SDK and others will). |
| 3 | Backward-compat root `docker-compose.yml` uses Compose v2 `include:` directive | Both live VPSes run modern Compose; trivial copy-paste fallback if needed. |
| 4 | Container names stay underscored (`sales_api`, `sales_worker`); marketing follows the same convention (`marketing_api`, `marketing_worker`) | Avoids orphaning live containers during rollout. Cosmetic rename can come later. |

## 4. Detailed move + rewrite plan

### 4A. File moves (use `git mv` to preserve history)

| From | To |
|---|---|
| `config.py` | `core/config.py` |
| `app/db.py` | `core/db.py` |
| `app/logging.py` | `core/logging.py` |
| `app/observability.py` | `core/observability.py` |
| `app/redis.py` | `core/redis.py` |
| `app/main.py` | `sales/app/main.py` |
| `app/cli.py` | `sales/app/cli.py` |
| `app/core/**` | `sales/app/core/**` |
| `app/services/**` | `sales/app/services/**` |
| `app/ui/**` | `sales/app/ui/**` |
| `app/templates/**` | `sales/app/templates/**` |
| `app/webhooks/**` | `sales/app/webhooks/**` |
| `app/workers/**` | `sales/app/workers/**` |
| `schemas.py` | `sales/schemas.py` |
| `001_initial.sql` … `008_simplify_to_inline_only.sql` | `sales/migrations/` |
| `tests/**` | `sales/tests/**` |
| `Dockerfile` | `sales/Dockerfile` (will edit) |
| `docker-compose.yml` | `deploy/compose.sales-only.yml` (will edit) |
| `docker-compose.dev.yml` | `deploy/compose.dev.yml` (will edit) |

Delete `app/` empty parent directory after all sub-moves complete.

### 4B. Python import rewrites

Run as one sed pass across all `*.py` files in `core/`, `sales/`, `marketing/`:

| Old | New |
|---|---|
| `from config import` | `from core.config import` |
| `from app.db import` | `from core.db import` |
| `from app.logging import` | `from core.logging import` |
| `from app.observability import` | `from core.observability import` |
| `from app.redis import` | `from core.redis import` |
| `from schemas import` | `from sales.schemas import` |
| `from app.cli import` | `from sales.app.cli import` |
| `from app.core` | `from sales.app.core` |
| `from app.services` | `from sales.app.services` |
| `from app.ui` | `from sales.app.ui` |
| `from app.webhooks` | `from sales.app.webhooks` |
| `from app.workers` | `from sales.app.workers` |

```bash
# One-shot rewrite script
find core sales marketing -name "*.py" -exec sed -i \
  -e 's|^from config import|from core.config import|g' \
  -e 's|^from app\.db import|from core.db import|g' \
  -e 's|^from app\.logging import|from core.logging import|g' \
  -e 's|^from app\.observability import|from core.observability import|g' \
  -e 's|^from app\.redis import|from core.redis import|g' \
  -e 's|^from schemas import|from sales.schemas import|g' \
  -e 's|^from app\.cli import|from sales.app.cli import|g' \
  -e 's|^from app\.core|from sales.app.core|g' \
  -e 's|^from app\.services|from sales.app.services|g' \
  -e 's|^from app\.ui|from sales.app.ui|g' \
  -e 's|^from app\.webhooks|from sales.app.webhooks|g' \
  -e 's|^from app\.workers|from sales.app.workers|g' \
  {} +
```

### 4C. String reference rewrites

These aren't `from … import` statements but module-path strings:

| Where | Old | New |
|---|---|---|
| Dockerfile CMD, compose `command:` | `uvicorn app.main:app` | `uvicorn sales.app.main:app` |
| compose `command:` for worker/beat/flower | `celery -A app.workers.celery_app …` | `celery -A sales.app.workers.celery_app …` |
| CLI invocation (docs + Makefile) | `python -m app.cli` | `python -m sales.app.cli` |
| `sales/app/main.py` Jinja2Templates init | `directory="app/templates"` | `directory="sales/app/templates"` |
| `sales/app/workers/celery_app.py` | `imports=["app.workers.tasks"]` | `imports=["sales.app.workers.tasks"]` |
| `sales/app/ui/routes.py` if it references static/templates path | check & update | check & update |

### 4D. Dockerfile (sales/Dockerfile)

```dockerfile
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root; the requirements/ dir is at the root.
COPY requirements/shared.txt requirements/sales.txt /build/
RUN pip install --prefix=/install -r shared.txt -r sales.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /install /usr/local

# Only sales + shared core land in the runtime image. No marketing/ on disk.
COPY --chown=app:app core /app/core
COPY --chown=app:app sales /app/sales

USER app

EXPOSE 8000

CMD ["uvicorn", "sales.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0) if urllib.request.urlopen('http://localhost:8000/health').status == 200 else sys.exit(1)" \
        || exit 1
```

### 4E. marketing/Dockerfile (skeleton)

Identical shape, swap `sales` for `marketing`:

```dockerfile
# (identical builder stage)

FROM python:3.12-slim AS runtime
# ... user + workdir setup ...

COPY --from=builder /install /usr/local
COPY --chown=app:app core /app/core
COPY --chown=app:app marketing /app/marketing

USER app
EXPOSE 8001       # different port to avoid conflict in combined bundle

CMD ["uvicorn", "marketing.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

`marketing/app/main.py` is a placeholder:

```python
"""Marketing Analyzer — milestone 2 skeleton."""
from fastapi import FastAPI

app = FastAPI(title="Marketing Analyzer", version="0.0.1")

@app.get("/health")
async def liveness() -> dict:
    return {"status": "ok"}

@app.get("/")
async def root() -> dict:
    return {"status": "marketing analyzer skeleton — not yet implemented"}
```

### 4F. deploy/compose.sales-only.yml

```yaml
# Sales-only deployment bundle. Canonical compose file for clients
# who purchased the Sales Call Analyzer product without Marketing.
#
# Fronted by Caddy via the shared external `web` network in production.
# See infra/caddy/README.md and NEW_VPS_ONBOARDING.md for host setup.

services:
  api:
    build:
      context: ..
      dockerfile: sales/Dockerfile
    image: ghcr.io/khaledggl/gogrowlabs-sales:stable
    container_name: sales_api
    command: uvicorn sales.app.main:app --host 0.0.0.0 --port 8000 --workers 2
    ports:
      - "127.0.0.1:8000:8000"
    env_file:
      - ../.env
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks: [default, web]

  worker:
    build:
      context: ..
      dockerfile: sales/Dockerfile
    image: ghcr.io/khaledggl/gogrowlabs-sales:stable
    container_name: sales_worker
    command: celery -A sales.app.workers.celery_app worker --loglevel=info --concurrency=4
    env_file:
      - ../.env
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks: [default]

  beat:
    build:
      context: ..
      dockerfile: sales/Dockerfile
    image: ghcr.io/khaledggl/gogrowlabs-sales:stable
    container_name: sales_beat
    command: celery -A sales.app.workers.celery_app beat --loglevel=info --schedule=/tmp/celerybeat-schedule
    env_file:
      - ../.env
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks: [default]

  redis:
    image: redis:7-alpine
    container_name: sales_redis
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped
    networks: [default]

  flower:
    build:
      context: ..
      dockerfile: sales/Dockerfile
    image: ghcr.io/khaledggl/gogrowlabs-sales:stable
    container_name: sales_flower
    command: celery -A sales.app.workers.celery_app flower --port=5555
    ports:
      - "127.0.0.1:5555:5555"
    env_file:
      - ../.env
    depends_on:
      redis:
        condition: service_healthy
    restart: unless-stopped
    networks: [default]

volumes:
  redis_data:

networks:
  default:
  web:
    name: web
    external: true
```

The `image:` tag enables Watchtower-style auto-pull on VPSes. The
`build:` block stays for local dev / CI builds.

### 4G. deploy/compose.marketing-only.yml (skeleton)

Same shape with `marketing_*` container names, `marketing/Dockerfile`,
`marketing.app.main:app`, port 8001 externally, separate redis instance
(`marketing_redis`) so the bundles can run independently on the same VPS.

### 4H. deploy/compose.combined.yml (skeleton)

Both products' app/worker/beat containers, **shared single Redis**,
**shared single Caddy**, **shared single beat scheduler** if practical
(or separate per-product beats for now; revisit during Phase 1).

### 4I. Backward-compat root docker-compose.yml

```yaml
# Backward-compat wrapper. The canonical sales-only compose file
# lives at deploy/compose.sales-only.yml. This file exists so that
# `docker compose up -d` at the repo root continues to work on
# already-deployed VPSes without changing their runbooks.
#
# To explicitly use a different bundle: docker compose -f deploy/compose.<bundle>.yml up -d
include:
  - deploy/compose.sales-only.yml
```

**Fallback if `include:` not supported on a given VPS's Compose version:**
copy the contents of `deploy/compose.sales-only.yml` into the root file
during rollout (one-time, per-VPS).

### 4J. Requirements split

`requirements/shared.txt`:
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
jinja2==3.1.4
pydantic==2.11.7
pydantic-settings==2.6.1
httpx==0.27.2
supabase==2.28.3
redis==5.2.0
python-json-logger==2.0.7
sentry-sdk[fastapi,celery]==2.18.0
```

`requirements/sales.txt`:
```
-r shared.txt
celery[redis]==5.4.0
flower==2.0.1
anthropic==0.39.0
slack-sdk==3.33.4
```

`requirements/marketing.txt`:
```
-r shared.txt
# Phase 1 will add: facebook-business (Meta Ads SDK), additional Slack deps, etc.
```

`requirements/dev.txt`:
```
-r sales.txt
-r marketing.txt
# test-time tools
pytest==... (whatever current requirements-dev.txt has)
```

Delete root-level `requirements.txt` and `requirements-dev.txt`.

### 4K. pytest.ini

```ini
[pytest]
testpaths = sales/tests marketing/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra -q --strict-markers
filterwarnings =
    ignore::DeprecationWarning:celery.*
    ignore::DeprecationWarning:kombu.*
```

### 4L. tests/conftest.py update (now sales/tests/conftest.py)

```python
# only change: import path
from core.config import get_settings  # noqa: E402
```

Add a minimal `marketing/tests/conftest.py` that sets the same env-var
stubs so any future marketing tests can run without env config:

```python
import os
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
# ... rest of the env stubs ...
from core.config import get_settings  # noqa: E402
get_settings.cache_clear()
```

### 4M. Makefile

```makefile
.PHONY: help up down dev logs build restart shell worker-shell ps clean test test-fast test-sales test-marketing install-dev

BUNDLE ?= sales-only
COMPOSE := docker compose -f deploy/compose.$(BUNDLE).yml

help:
	@echo "Targets:"
	@echo "  make up            — start services (BUNDLE=sales-only|marketing-only|combined, default sales-only)"
	@echo "  make dev           — start with hot-reload overlay"
	@echo "  make down          — stop all services"
	@echo "  make build         — rebuild images for current bundle"
	@echo "  make logs          — tail logs"
	@echo "  make shell         — exec into the api container (sales-only or sales side of combined)"
	@echo "  make test          — run all tests (sales + marketing)"
	@echo "  make test-sales    — run sales tests only"
	@echo "  make test-marketing — run marketing tests only"

up:        ; $(COMPOSE) up -d
dev:       ; $(COMPOSE) -f deploy/compose.dev.yml up
down:      ; $(COMPOSE) down
build:     ; $(COMPOSE) build
logs:      ; $(COMPOSE) logs -f --tail=100
shell:     ; $(COMPOSE) exec sales_api /bin/bash
ps:        ; $(COMPOSE) ps
clean:     ; $(COMPOSE) down -v

install-dev:
	pip install -r requirements/dev.txt

test:           ; pytest
test-fast:      ; pytest -x --ff
test-sales:     ; pytest sales/tests
test-marketing: ; pytest marketing/tests
```

### 4N. CI workflow (.github/workflows/ci.yml)

Updates needed:
- `cache-dependency-path` → `requirements/shared.txt`, `requirements/sales.txt`, `requirements/marketing.txt`, `requirements/dev.txt`
- Install step → `pip install -r requirements/dev.txt`
- docker-build job builds both `sales/Dockerfile` and `marketing/Dockerfile`

### 4O. New workflow .github/workflows/publish-images.yml

```yaml
name: Publish Images

on:
  push:
    branches: [master]

permissions:
  contents: read
  packages: write

jobs:
  publish:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        product: [sales, marketing]
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - uses: docker/build-push-action@v6
        with:
          context: .
          file: ${{ matrix.product }}/Dockerfile
          push: true
          tags: |
            ghcr.io/khaledggl/gogrowlabs-${{ matrix.product }}:${{ github.sha }}
            ghcr.io/khaledggl/gogrowlabs-${{ matrix.product }}:stable
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### 4P. Doc updates

- `CLAUDE.md` — replace "Project Structure" section + "Running" section to reflect new layout; document `BUNDLE=...` Makefile usage
- `INSTALL.md` — search/replace `app/` → `sales/app/`, `config.py` → `core/config.py`, etc.
- `NEW_VPS_ONBOARDING.md` — compose file path references update; document Watchtower install step
- `ONBOARDING.md` — same compose path updates
- `STATUS.md` — append note that Phase 0 is complete (after this PR merges)

## 5. Commit sequence (single PR)

| # | Commit message | Contents |
|---|---|---|
| 1 | `Refactor: extract core/, move app/ → sales/, requirements split` | All file moves + import rewrites + Dockerfile path + compose path updates + pytest.ini. End state: `make up` brings up sales stack identical to before; all 259 tests pass. |
| 2 | `Add: deploy/ bundles + marketing/ skeleton + backward-compat root compose` | `deploy/compose.{sales-only,marketing-only,combined,dev}.yml` + `marketing/` hello-world + root `docker-compose.yml` include wrapper. |
| 3 | `Add: GHCR image publishing workflow` | `.github/workflows/publish-images.yml` and updated `ci.yml`. |
| 4 | `Docs: update CLAUDE / INSTALL / ONBOARDING / NEW_VPS_ONBOARDING for new structure` | All doc updates in one commit for review clarity. |

## 6. Verification checklist (PR before merge)

- [ ] `pytest` passes — all 259 tests
- [ ] `pytest sales/tests` passes in isolation
- [ ] `pytest marketing/tests` runs (zero tests, but conftest loads cleanly)
- [ ] `docker compose -f deploy/compose.sales-only.yml build` succeeds
- [ ] `docker compose -f deploy/compose.sales-only.yml up -d` starts cleanly
- [ ] `curl http://localhost:8000/health` returns `{"status":"ok"}`
- [ ] `curl http://localhost:8000/health/ready` returns `{"status":"ready"}` (with real env)
- [ ] `docker compose -f deploy/compose.marketing-only.yml build` succeeds (marketing hello-world)
- [ ] `docker compose -f deploy/compose.combined.yml build` succeeds
- [ ] Root `docker compose up -d` (backward-compat wrapper) brings up sales stack identical to before
- [ ] `make up`, `make dev`, `make test`, `make test-sales` all work with no args
- [ ] GHCR workflow publishes test images on a feature-branch push (manually trigger to verify)
- [ ] CI green on the PR
- [ ] Manual webhook smoke test in local dev: post a transcript-ready payload, see it scored, see Slack message

## 7. Live VPS rollout (one-time after merge)

Per VPS (gogrowlabs first, then calivus):

```bash
ssh root@<vps-ip>
cd /srv/salesagent     # or /srv/sales on calivus

# Save current state in case rollback needed
git rev-parse HEAD > /tmp/pre-phase0-sha

# Pull new code
git fetch origin
git checkout master
git pull

# Rebuild image (one-time; Watchtower will handle future updates)
docker compose build

# Rolling restart
docker compose up -d

# Verify
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/health/ready

# External — adjust hostname per VPS
curl -fsS https://calivus.gogrowlabs.com/health   # or .../salesgrader/health on gogrowlabs

# Watchtower install (one-time per VPS) — see updated NEW_VPS_ONBOARDING.md
docker run -d \
  --name watchtower \
  --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  --schedule "0 0 4 * * *" \
  --cleanup \
  --label-enable
```

After rollout: existing GHL webhook still hits the same URL; Caddy
routing is unchanged; Supabase migrations are untouched; data is
unaffected. The only observable change is that the container's
internal code paths are now `sales.app.*` instead of `app.*`.

## 8. Rollback plan

If something breaks after the merge or after a live VPS rollout:

**Quick rollback (per VPS, ~30 seconds):**
```bash
ssh root@<vps-ip>
cd /srv/salesagent
git checkout $(cat /tmp/pre-phase0-sha)
docker compose down
docker compose up -d --build
```

**Repo rollback (revert merge commit):**
```bash
git revert -m 1 <phase-0-merge-commit-sha>
git push
# VPSes pull on next Watchtower tick, or run the per-VPS quick rollback
```

**Why rollback is safe:**
- No SQL migrations changed → Supabase data is untouched
- No environment variables changed → secrets remain valid
- Caddy config unchanged → external URLs still route correctly
- Container names unchanged → no orphaned containers
- Webhook URLs unchanged → GHL keeps delivering

## 9. Known risks + mitigations

| Risk | Mitigation |
|---|---|
| sed import-rewrite misses an edge case (e.g. a `from app . cli` with weird spacing) | Run `pytest --collect-only` after rewrite to surface all import errors before committing |
| `Jinja2Templates(directory="app/templates")` string reference not caught by import rewrite | Manual grep for `"app/` and `'app/'` strings after sed pass |
| Compose v2 `include:` not supported on a VPS | Fallback: copy contents of `deploy/compose.sales-only.yml` into root `docker-compose.yml` during rollout (5 sec fix) |
| GHCR image push permission denied | First push will require `GITHUB_TOKEN` with `packages: write` — already in workflow file but verify on first run |
| `infra/caddy/Caddyfile` references container names | Caddy uses `sales_api:8000` (Docker DNS) — container name preserved, no change needed; verify after rollout |
| Watchtower aggressively restarts during a Celery task | Schedule it for 4am UTC (low-traffic window); set `--include-stopped=false` |

## 10. After Phase 0 ships

- Update `STATUS.md` to mark Phase 0 complete and link to this doc
- Add memory entry "Phase 0 done, ready for Phase 1 Week 1 (marketing schema + identity resolver)"
- Delete this doc (`PHASE_0_REFACTOR_PLAN.md`) — it's executed and the code is now the source of truth. Or move to `docs/archive/` if you want to keep the historical record.

---

**Ready to execute when you give the word.** First step on execute: create a feature branch (`refactor/phase-0-modular-monorepo`), begin with commit 1.
