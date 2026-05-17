-- ─────────────────────────────────────────────────────────────
-- 005_ai_outcome.sql
-- Transcript-based outcome detection: Claude classifies each
-- call as sold / not_sold / follow_up and returns a confidence
-- score plus a one-sentence evidence quote. This replaces the
-- previous flow where outcome was read from a GHL contact
-- custom field that reps populate after the call (often blank
-- at scoring time, leading to undercounted closes).
--
-- NOTE: ALTER TYPE ... ADD VALUE cannot run inside a transaction.
-- If your migration runner wraps everything in a tx, run the
-- enum line first as its own statement.
-- ─────────────────────────────────────────────────────────────

alter type call_outcome add value if not exists 'follow_up';

alter table call_scores
    add column if not exists outcome_confidence numeric(3,2)
        check (outcome_confidence is null or (outcome_confidence >= 0 and outcome_confidence <= 1)),
    add column if not exists outcome_evidence text;
