-- ─────────────────────────────────────────────────────────────
-- 006_enable_rls.sql
-- Defense-in-depth security posture for the public schema.
--
-- Two distinct fixes for two distinct Supabase advisor warnings:
--
-- 1. Tables: enable RLS so that if the anon key is ever exposed,
--    the default deny-all behavior keeps rows private until an
--    explicit policy is added. The app uses the service role key
--    (BYPASSRLS) so behavior is unchanged.
--
-- 2. Views: set security_invoker = on so each view runs with the
--    caller's permissions instead of the view owner's. Without
--    this, views would bypass RLS on the underlying tables —
--    making step 1 above ineffective for any client reading
--    through a view.
--
-- We deliberately do NOT add any RLS policies. Empty RLS means
-- only the service role can read or write. That's the desired
-- posture for a backend-only application.
-- ─────────────────────────────────────────────────────────────

-- ── Tables ───────────────────────────────────────────────────

alter table reps              enable row level security;
alter table calls             enable row level security;
alter table call_scores       enable row level security;
alter table coaching_moments  enable row level security;
alter table call_objections   enable row level security;
alter table scoring_framework enable row level security;
alter table rep_kpi_snapshots enable row level security;

-- ── Views (security_invoker forces RLS on underlying tables) ─

alter view v_rep_performance_30d     set (security_invoker = on);
alter view v_cold_warm_comparison    set (security_invoker = on);
alter view v_therapist_mode_trend    set (security_invoker = on);
alter view v_rep_performance_weekly  set (security_invoker = on);
alter view v_weekly_overview         set (security_invoker = on);
alter view v_top_objections_weekly   set (security_invoker = on);
alter view v_weekly_objections       set (security_invoker = on);
alter view v_weekly_ai_summaries     set (security_invoker = on);
alter view v_weekly_coaching_moments set (security_invoker = on);
alter view v_weekly_source_performance set (security_invoker = on);
