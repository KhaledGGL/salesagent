-- ─────────────────────────────────────────────────────────────
-- 008_simplify_to_inline_only.sql
-- Drop the legacy GHL Conversations API ingestion path.
--
-- The inline-transcript webhook (/webhooks/ghl/transcript-ready) is now
-- the sole ingestion model. Lead-source attribution comes from UTM merge
-- tags in the webhook payload instead of a follow-up GHL Contacts API
-- fetch — more granular (campaign + creative + keyword level), one fewer
-- moving part, and clients no longer need to issue a GHL API token.
--
-- Lead temperature (cold/warm) is now computed from our own `calls`
-- history at insert time rather than read from the GHL contact's
-- `dateAdded`. Self-contained, more accurate (catches returning leads),
-- zero added GHL workflow config.
-- ─────────────────────────────────────────────────────────────

-- ── Add UTM attribution columns ──────────────────────────────

alter table calls add column if not exists utm_source   text;
alter table calls add column if not exists utm_medium   text;
alter table calls add column if not exists utm_campaign text;
alter table calls add column if not exists utm_content  text;
alter table calls add column if not exists utm_term     text;

-- ── Drop columns no longer populated ─────────────────────────
-- ghl_conversation_id and recording_url were only set by the legacy
-- /ghl/call-completed → fetch_transcript path (now removed). call_type
-- was a custom field nobody actually used; Claude can infer call type
-- from the transcript itself.

alter table calls drop column if exists ghl_conversation_id;
alter table calls drop column if exists recording_url;
alter table calls drop column if exists call_type;

-- ── Drop unused enum (must come AFTER the column drop) ───────

drop type if exists call_type;

-- ── Indexes for marketing analytics ──────────────────────────
-- These two are the natural filter axes for source-quality questions:
--   "What's the close rate for utm_source='facebook'?"
--   "Which utm_campaign produces the lowest-objection leads?"

create index if not exists idx_calls_utm_source   on calls (utm_source);
create index if not exists idx_calls_utm_campaign on calls (utm_campaign);
