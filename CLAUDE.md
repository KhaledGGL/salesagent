# Sales Call Analyzer — Project Guide

> **Current status lives in [`STATUS.md`](./STATUS.md).** Read that first for
> what's done, what's pending, and how to resume. This file covers stable
> conventions only.

## Stack
- **API:** FastAPI (uvicorn)
- **Task queue:** Celery with Redis broker
- **Database:** Supabase (Postgres) via `supabase-py`
- **AI:** Anthropic Claude API
- **Notifications:** Slack Bot

## Project Structure
```
app/
  main.py              # FastAPI entrypoint
  db.py                # Supabase client singleton
  webhooks/ghl.py      # GHL webhook receiver
  services/            # External API clients (GHL, Claude, Slack)
  workers/
    celery_app.py      # Celery config
    tasks.py           # Celery tasks
config.py              # pydantic-settings config
schemas.py             # Pydantic models & enums
```

## Conventions
- HTTP client: `httpx` (never `requests`)
- Settings: always via `config.settings`, never raw `os.getenv`
- DB access: always via `app.db.get_supabase()`, never direct client creation
- Pydantic models for all API boundaries (webhook payloads, Claude output)
- Celery tasks use `bind=True`, `acks_late`, and retry with backoff
- Enums defined once in `schemas.py`, mirrored in SQL

## Running
```bash
docker compose up          # API + worker + beat + Redis + Flower
# API:    http://localhost:8000
# Flower: http://localhost:5555
```

## Environment
- Copy `.env.example` to `.env` and fill in real values
- Never commit `.env`
