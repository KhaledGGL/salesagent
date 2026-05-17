-- ─────────────────────────────────────────────────────────────
-- 004_coaching_marketing_views.sql
-- Views that feed the weekly coaching lesson and marketing
-- intelligence reports. Same "previous completed week" window
-- as 003_weekly_views.sql (Monday 00:00 → Sunday 23:59:59).
-- ─────────────────────────────────────────────────────────────

-- ── Coaching moments with context ─────────────────────────────
-- All coaching moments from the previous week, enriched with
-- rep name, call outcome, overall score, and lead source so
-- Claude can identify patterns across reps and categories.

create or replace view v_weekly_coaching_moments as
select
    r.name                  as rep_name,
    cm.category::text       as category,
    cm.severity::text       as severity,
    cm.note                 as note,
    c.outcome::text         as outcome,
    cs.overall_score        as overall_score,
    c.lead_source::text     as lead_source
from coaching_moments cm
join calls c   on c.id = cm.call_id
join reps r    on r.id = c.rep_id
join call_scores cs on cs.call_id = c.id
where c.called_at >= date_trunc('week', now()) - interval '1 week'
  and c.called_at <  date_trunc('week', now())
  and c.status = 'scored';


-- ── AI summaries + win/loss moments ───────────────────────────
-- Per-call AI summaries and pivotal moments for the previous
-- week. Used by the marketing intelligence report to extract
-- prospect language, pain points, and positioning gaps.

create or replace view v_weekly_ai_summaries as
select
    r.name                  as rep_name,
    cs.ai_summary           as ai_summary,
    cs.win_loss_description as win_loss_description,
    cs.overall_score        as overall_score,
    c.outcome::text         as outcome,
    c.lead_source::text     as lead_source,
    c.lead_temperature::text as lead_temperature
from call_scores cs
join calls c on c.id = cs.call_id
join reps r  on r.id = c.rep_id
where c.called_at >= date_trunc('week', now()) - interval '1 week'
  and c.called_at <  date_trunc('week', now())
  and c.status = 'scored';


-- ── Source performance for the previous week ──────────────────
-- Close rate and average score broken down by lead source.
-- Pre-aggregated so the marketing intel prompt gets clean stats.

create or replace view v_weekly_source_performance as
select
    c.lead_source::text                      as lead_source,
    count(c.id)                              as total_calls,
    count(c.id) filter (
        where c.outcome = 'sold'
    )                                        as sold_calls,
    round(
        count(c.id) filter (where c.outcome = 'sold') * 100.0
        / nullif(count(c.id), 0), 1
    )                                        as close_rate_pct,
    round(avg(cs.overall_score), 2)          as avg_overall_score
from calls c
left join call_scores cs on cs.call_id = c.id
where c.called_at >= date_trunc('week', now()) - interval '1 week'
  and c.called_at <  date_trunc('week', now())
  and c.status = 'scored'
  and c.lead_source is not null
group by c.lead_source;
