-- ─────────────────────────────────────────────────────────────
-- 007_weekly_reports.sql
-- Persist the three weekly Claude-generated reports (sales /
-- coaching lesson / marketing intel) so the management UI can
-- surface them historically without re-running Claude on every
-- page load.
--
-- Today these reports go to Slack and disappear into the channel
-- scroll — every Monday's narrative is lost from a queryability
-- standpoint. This table captures the JSON payload as it's posted
-- so the UI's reports archive + dashboard "latest insights" cards
-- can read directly.
--
-- The unique constraint on (report_type, week_start) makes the
-- upsert idempotent — Celery task retries can't create duplicate
-- rows, and a manual replay of a past Monday simply overwrites
-- (matching the existing rep_kpi_snapshots upsert pattern).
-- ─────────────────────────────────────────────────────────────

create type weekly_report_type as enum ('sales', 'coaching', 'marketing');

create table weekly_reports (
    id           uuid primary key default uuid_generate_v4(),
    report_type  weekly_report_type not null,
    week_start   date not null,
    week_end     date not null,
    payload      jsonb not null,
    created_at   timestamptz not null default now(),
    unique (report_type, week_start)
);

create index idx_weekly_reports_type_date
    on weekly_reports (report_type, week_start desc);

-- RLS: same posture as 006_enable_rls — service role only, no policies.
alter table weekly_reports enable row level security;
