-- ─────────────────────────────────────────────────────────────
-- 001_initial.sql
-- Run once against your Supabase project.
-- ─────────────────────────────────────────────────────────────

-- Extensions
create extension if not exists "uuid-ossp";

-- ── Enums ────────────────────────────────────────────────────

create type lead_source      as enum ('meta', 'google', 'organic');
create type lead_temperature as enum ('cold', 'warm');
create type call_type        as enum ('discovery', 'treatment_plan');
create type call_outcome     as enum ('sold', 'not_sold', 'no_show', 'rescheduled');
create type call_status      as enum ('received', 'fetching', 'queued', 'scoring', 'scored', 'failed');
create type objection_type   as enum ('price', 'time', 'spouse', 'trust', 'urgency', 'competitor', 'fear', 'other');
create type handling_quality as enum ('poor', 'fair', 'good', 'excellent');
create type coaching_category as enum ('rapport', 'diagnosis', 'objection_handling', 'close', 'compliance');
create type severity         as enum ('low', 'medium', 'high');
create type kpi_period       as enum ('30d', '60d', '90d', 'weekly');

-- ── Reps ─────────────────────────────────────────────────────

create table reps (
    id            uuid primary key default uuid_generate_v4(),
    ghl_user_id   text not null unique,
    name          text not null,
    email         text,
    is_active     boolean not null default true,
    created_at    timestamptz not null default now()
);

create index idx_reps_ghl_user_id on reps (ghl_user_id);

-- ── Calls ────────────────────────────────────────────────────

create table calls (
    id                uuid primary key default uuid_generate_v4(),
    rep_id            uuid not null references reps(id) on delete restrict,
    ghl_contact_id    text not null,
    ghl_message_id    text not null unique,
    ghl_conversation_id text,
    lead_name         text,
    lead_source       lead_source,
    lead_temperature  lead_temperature,
    call_type         call_type,
    outcome           call_outcome,
    recording_url     text,
    transcript        text,
    duration_seconds  integer,
    called_at         timestamptz,
    status            call_status not null default 'received',
    error_message     text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);

create index idx_calls_rep_id      on calls (rep_id);
create index idx_calls_lead_source on calls (lead_source);
create index idx_calls_called_at   on calls (called_at desc);
create index idx_calls_status      on calls (status);
create index idx_calls_ghl_msg     on calls (ghl_message_id);

-- Auto-update updated_at
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create trigger calls_updated_at
    before update on calls
    for each row execute function set_updated_at();

-- ── Call Scores ───────────────────────────────────────────────

create table call_scores (
    id                   uuid primary key default uuid_generate_v4(),
    call_id              uuid not null unique references calls(id) on delete cascade,
    rapport_score        smallint not null check (rapport_score between 1 and 10),
    diagnosis_score      smallint not null check (diagnosis_score between 1 and 10),
    objection_score      smallint not null check (objection_score between 1 and 10),
    close_score          smallint not null check (close_score between 1 and 10),
    compliance_score     smallint not null check (compliance_score between 1 and 10),
    overall_score        smallint not null check (overall_score between 1 and 10),
    therapist_mode_flag  boolean not null default false,
    therapist_mode_reason text,
    win_loss_timestamp   integer,
    win_loss_description text,
    ai_summary           text not null,
    scored_at            timestamptz not null default now()
);

create index idx_call_scores_call_id on call_scores (call_id);

-- ── Coaching Moments ──────────────────────────────────────────

create table coaching_moments (
    id                uuid primary key default uuid_generate_v4(),
    call_id           uuid not null references calls(id) on delete cascade,
    timestamp_seconds integer not null,
    category          coaching_category not null,
    severity          severity not null,
    note              text not null,
    created_at        timestamptz not null default now()
);

create index idx_coaching_call_id  on coaching_moments (call_id);
create index idx_coaching_severity on coaching_moments (severity);

-- ── Call Objections ───────────────────────────────────────────

create table call_objections (
    id                uuid primary key default uuid_generate_v4(),
    call_id           uuid not null references calls(id) on delete cascade,
    timestamp_seconds integer not null,
    objection_type    objection_type not null,
    objection_text    text not null,
    handling_quality  handling_quality not null,
    created_at        timestamptz not null default now()
);

create index idx_objections_call_id on call_objections (call_id);
create index idx_objections_type    on call_objections (objection_type);

-- ── Scoring Framework ─────────────────────────────────────────

create table scoring_framework (
    id          uuid primary key default uuid_generate_v4(),
    category    coaching_category not null,
    name        text not null,
    description text not null,
    rubric_low  text not null,   -- 1-3 description
    rubric_mid  text not null,   -- 4-6 description
    rubric_high text not null,   -- 7-10 description
    weight      numeric(4,2) not null default 0.20,
    is_active   boolean not null default true,
    created_at  timestamptz not null default now()
);

-- ── Rep KPI Snapshots ─────────────────────────────────────────

create table rep_kpi_snapshots (
    id                   uuid primary key default uuid_generate_v4(),
    rep_id               uuid not null references reps(id) on delete cascade,
    snapshot_date        date not null,
    period               kpi_period not null,
    total_calls          integer not null default 0,
    sold_calls           integer not null default 0,
    close_rate           numeric(5,2),
    avg_overall_score    numeric(4,2),
    avg_rapport          numeric(4,2),
    avg_diagnosis        numeric(4,2),
    avg_objection        numeric(4,2),
    avg_close            numeric(4,2),
    avg_compliance       numeric(4,2),
    therapist_mode_count integer not null default 0,
    cold_calls           integer not null default 0,
    warm_calls           integer not null default 0,
    cold_close_rate      numeric(5,2),
    warm_close_rate      numeric(5,2),
    created_at           timestamptz not null default now(),
    unique (rep_id, snapshot_date, period)
);

create index idx_kpi_rep_id        on rep_kpi_snapshots (rep_id);
create index idx_kpi_snapshot_date on rep_kpi_snapshots (snapshot_date desc);
