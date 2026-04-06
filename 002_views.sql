-- ─────────────────────────────────────────────────────────────
-- 002_views.sql
-- Analytical views for reports and dashboards.
-- ─────────────────────────────────────────────────────────────

-- ── Weekly objection frequency by lead source ─────────────────

create or replace view v_weekly_objections as
select
    date_trunc('week', c.called_at)::date   as week_start,
    c.lead_source,
    o.objection_type,
    count(*)                                 as frequency,
    round(
        count(*) * 100.0 /
        sum(count(*)) over (
            partition by date_trunc('week', c.called_at)::date, c.lead_source
        ), 1
    )                                        as pct_of_source
from call_objections o
join calls c on c.id = o.call_id
where c.called_at is not null
group by date_trunc('week', c.called_at)::date, c.lead_source, o.objection_type;

-- ── Rep performance summary (rolling 30 days) ─────────────────

create or replace view v_rep_performance_30d as
select
    r.id                                     as rep_id,
    r.name                                   as rep_name,
    count(c.id)                              as total_calls,
    count(c.id) filter (
        where c.outcome = 'sold'
    )                                        as sold_calls,
    round(
        count(c.id) filter (where c.outcome = 'sold') * 100.0
        / nullif(count(c.id), 0), 1
    )                                        as close_rate_pct,
    round(avg(cs.overall_score), 2)          as avg_overall_score,
    round(avg(cs.rapport_score), 2)          as avg_rapport,
    round(avg(cs.diagnosis_score), 2)        as avg_diagnosis,
    round(avg(cs.objection_score), 2)        as avg_objection,
    round(avg(cs.close_score), 2)            as avg_close,
    round(avg(cs.compliance_score), 2)       as avg_compliance,
    count(cs.id) filter (
        where cs.therapist_mode_flag = true
    )                                        as therapist_mode_count
from reps r
left join calls c
    on c.rep_id = r.id
    and c.called_at >= now() - interval '30 days'
    and c.status = 'scored'
left join call_scores cs on cs.call_id = c.id
where r.is_active = true
group by r.id, r.name;

-- ── Cold vs warm comparison per rep ──────────────────────────

create or replace view v_cold_warm_comparison as
select
    r.name                                   as rep_name,
    c.lead_temperature,
    count(c.id)                              as total_calls,
    round(
        count(c.id) filter (where c.outcome = 'sold') * 100.0
        / nullif(count(c.id), 0), 1
    )                                        as close_rate_pct,
    round(avg(cs.overall_score), 2)          as avg_score,
    round(avg(cs.diagnosis_score), 2)        as avg_diagnosis,
    round(avg(cs.objection_score), 2)        as avg_objection
from reps r
join calls c on c.rep_id = r.id
join call_scores cs on cs.call_id = c.id
where c.status = 'scored'
  and c.called_at >= now() - interval '90 days'
group by r.name, c.lead_temperature;

-- ── Therapist mode trend ──────────────────────────────────────

create or replace view v_therapist_mode_trend as
select
    date_trunc('week', c.called_at)::date   as week_start,
    r.name                                   as rep_name,
    count(c.id)                              as total_calls,
    count(cs.id) filter (
        where cs.therapist_mode_flag = true
    )                                        as therapist_mode_calls,
    round(
        count(cs.id) filter (
            where cs.therapist_mode_flag = true
        ) * 100.0 / nullif(count(c.id), 0), 1
    )                                        as therapist_mode_pct
from calls c
join reps r on r.id = c.rep_id
join call_scores cs on cs.call_id = c.id
where c.status = 'scored'
  and c.called_at is not null
group by 1, 2
order by 1 desc, 2;
