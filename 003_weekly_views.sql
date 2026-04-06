-- ─────────────────────────────────────────────────────────────
-- 003_weekly_views.sql
-- Views that compute stats for the PREVIOUS COMPLETED WEEK
-- (Monday 00:00 → Sunday 23:59:59 in Postgres's locale week).
--
-- Design: we deliberately resolve "last week" inside the views using
-- date_trunc so the beat task can be timezone-agnostic and idempotent.
-- ─────────────────────────────────────────────────────────────

-- ── Per-rep performance for last completed week ─────────────

create or replace view v_rep_performance_weekly as
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
    and c.called_at >= date_trunc('week', now()) - interval '1 week'
    and c.called_at <  date_trunc('week', now())
    and c.status = 'scored'
left join call_scores cs on cs.call_id = c.id
where r.is_active = true
group by r.id, r.name;


-- ── Org-wide weekly overview ────────────────────────────────

create or replace view v_weekly_overview as
select
    (date_trunc('week', now()) - interval '1 week')::date as week_start,
    (date_trunc('week', now()) - interval '1 day')::date  as week_end,
    count(c.id)                              as total_calls,
    count(c.id) filter (
        where c.outcome = 'sold'
    )                                        as sold_calls,
    round(
        count(c.id) filter (where c.outcome = 'sold') * 100.0
        / nullif(count(c.id), 0), 1
    )                                        as close_rate_pct,
    round(avg(cs.overall_score), 2)          as avg_overall_score,
    count(cs.id) filter (
        where cs.therapist_mode_flag = true
    )                                        as therapist_mode_count
from calls c
left join call_scores cs on cs.call_id = c.id
where c.called_at >= date_trunc('week', now()) - interval '1 week'
  and c.called_at <  date_trunc('week', now())
  and c.status = 'scored';


-- ── Top objections for last completed week ─────────────────
-- Ranked by raw frequency. Broken down by lead_source for attribution.

create or replace view v_top_objections_weekly as
select
    o.objection_type,
    c.lead_source,
    count(*)                                 as frequency,
    round(
        count(*) * 100.0 /
        sum(count(*)) over (), 1
    )                                        as pct_of_total
from call_objections o
join calls c on c.id = o.call_id
where c.called_at >= date_trunc('week', now()) - interval '1 week'
  and c.called_at <  date_trunc('week', now())
  and c.status = 'scored'
group by o.objection_type, c.lead_source
order by frequency desc;
