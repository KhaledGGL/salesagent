"""Celery tasks — call processing pipeline.

Pipeline:
    webhook → process_call → score_call → (slack, later)

process_call: fetch transcript + enrich lead metadata from GHL contact
score_call:   send transcript to Claude, persist scorecard + moments + objections
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import ValidationError

from app.core.report_blocks import build_weekly_fallback_text, build_weekly_report_blocks
from app.core.slack_blocks import (
    build_coaching_moment_block,
    build_fallback_text,
    build_objections_summary_block,
    build_scorecard_blocks,
)
from app.db import get_supabase
from app.services.claude_client import TranscriptTooShortError, score_transcript
from app.services.ghl_client import fetch_transcript, get_contact, map_ghl_source
from app.services.slack_client import post_message
from app.workers.celery_app import celery_app
from config import settings
from schemas import ScorecardOutput

logger = logging.getLogger(__name__)


def _update_call(call_id: str, **fields) -> None:
    get_supabase().table("calls").update(fields).eq("id", call_id).execute()


# ── Lead enrichment helpers ──────────────────────────────────────────────────

def _derive_lead_temperature(contact: dict[str, Any]) -> str:
    """Warm if contact has been in GHL for >30 days (prior relationship), else cold."""
    date_added = contact.get("dateAdded")
    if not date_added:
        return "cold"
    try:
        added_dt = datetime.fromisoformat(date_added.replace("Z", "+00:00"))
    except ValueError:
        return "cold"
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    return "warm" if added_dt < cutoff else "cold"


def _custom_field(contact: dict[str, Any], key: str, default: str) -> str:
    """Safe access to a GHL contact custom field (handles list-of-dicts and dict shapes)."""
    cf = contact.get("customFields") or contact.get("custom_fields") or {}
    if isinstance(cf, dict):
        return str(cf.get(key) or default).lower()
    if isinstance(cf, list):
        for item in cf:
            if item.get("key") == key or item.get("id") == key:
                return str(item.get("value") or default).lower()
    return default


def _enrich_from_contact(contact: dict[str, Any]) -> dict[str, Any]:
    """Map GHL contact → columns on the calls table."""
    first = contact.get("firstName") or ""
    last = contact.get("lastName") or ""
    lead_name = (f"{first} {last}").strip() or contact.get("name") or None

    return {
        "lead_name": lead_name,
        "lead_source": map_ghl_source(contact.get("source", "")),
        "lead_temperature": _derive_lead_temperature(contact),
        "call_type": _custom_field(contact, "call_type", "discovery"),
        "outcome": _custom_field(contact, "call_outcome", "not_sold"),
    }


# ── Task: process_call ───────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="process_call",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_call(self, call_id: str, message_id: str) -> dict:
    """Fetch transcript + enrich lead metadata from GHL, then enqueue scoring.

    Status transitions: received → fetching → queued
    """
    logger.info("process_call started: call_id=%s message_id=%s", call_id, message_id)

    try:
        _update_call(call_id, status="fetching")

        # ── Detect inline-transcript fast path ───────────────────────────
        # The /webhooks/ghl/transcript-ready endpoint inserts the call row
        # with the transcript already populated. In that case we skip the
        # GHL message fetch entirely and only do contact enrichment.
        existing_row = (
            get_supabase()
            .table("calls")
            .select("transcript, ghl_contact_id")
            .eq("id", call_id)
            .single()
            .execute()
        )
        existing_transcript = (existing_row.data or {}).get("transcript")
        contact_id = (existing_row.data or {}).get("ghl_contact_id")

        if existing_transcript:
            logger.info(
                "Inline transcript detected for call_id=%s (%d chars) — skipping GHL fetch",
                call_id, len(existing_transcript),
            )
            transcript = existing_transcript
            result: dict[str, Any] = {
                "transcript": transcript,
                "recording_url": None,
                "duration_seconds": None,
                "called_at": None,
            }
        else:
            # ── 2-step transcript fetch from GHL ─────────────────────────
            result = fetch_transcript(message_id)
            transcript = result["transcript"]

            if not transcript:
                _update_call(
                    call_id,
                    status="failed",
                    error_message="No transcript returned from GHL",
                    recording_url=result.get("recording_url"),
                )
                logger.warning("No transcript for call_id=%s", call_id)
                return {"call_id": call_id, "status": "failed", "reason": "no_transcript"}

        enrichment: dict[str, Any] = {}
        try:
            contact = get_contact(contact_id)
            enrichment = _enrich_from_contact(contact)
        except Exception as exc:
            logger.warning("Contact enrichment failed for %s: %s", contact_id, exc)

        # ── Persist everything ───────────────────────────────────────────
        update_fields: dict[str, Any] = {
            "transcript": transcript,
            "status": "queued",
            **enrichment,
        }
        if result["recording_url"]:
            update_fields["recording_url"] = result["recording_url"]
        if result["duration_seconds"]:
            update_fields["duration_seconds"] = result["duration_seconds"]
        if result["called_at"]:
            update_fields["called_at"] = result["called_at"]

        _update_call(call_id, **update_fields)
        logger.info("Transcript + enrichment saved for call_id=%s", call_id)

        # ── Enqueue scoring ──────────────────────────────────────────────
        score_call.delay(call_id)
        logger.info("Enqueued score_call for call_id=%s", call_id)

        return {"call_id": call_id, "status": "queued"}

    except Exception as exc:
        logger.error("process_call failed: call_id=%s error=%s", call_id, exc, exc_info=True)
        _update_call(call_id, status="failed", error_message=str(exc)[:500])
        raise


# ── Task: score_call ─────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="score_call",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def score_call(self, call_id: str) -> dict:
    """Send transcript to Claude, validate, and persist the scorecard.

    Status transitions: queued → scoring → scored (or failed)
    """
    logger.info("score_call started: call_id=%s", call_id)
    db = get_supabase()

    try:
        _update_call(call_id, status="scoring")

        # ── Load call + rep ──────────────────────────────────────────────
        call_resp = (
            db.table("calls")
            .select("*, reps(name)")
            .eq("id", call_id)
            .single()
            .execute()
        )
        call = call_resp.data
        if not call.get("transcript"):
            raise ValueError("Call has no transcript — cannot score")

        rep_name = (call.get("reps") or {}).get("name", "Unknown")

        # ── Call Claude ──────────────────────────────────────────────────
        try:
            scorecard: ScorecardOutput = score_transcript(
                transcript=call["transcript"],
                rep_name=rep_name,
                lead_name=call.get("lead_name"),
                lead_source=call.get("lead_source"),
                lead_temperature=call.get("lead_temperature"),
                call_type=call.get("call_type"),
                outcome=call.get("outcome"),
                duration_seconds=call.get("duration_seconds"),
            )
        except TranscriptTooShortError as exc:
            _update_call(
                call_id,
                status="failed",
                error_message=f"Claude rejected transcript: {exc}",
            )
            logger.warning("Transcript rejected for call_id=%s: %s", call_id, exc)
            return {"call_id": call_id, "status": "failed", "reason": "rejected"}
        except ValidationError as exc:
            # Prompt drift — log separately so we can catch it early
            logger.error("SCORE_DRIFT call_id=%s validation_errors=%s", call_id, exc.errors())
            raise

        # ── Persist scorecard ────────────────────────────────────────────
        db.table("call_scores").insert({
            "call_id": call_id,
            "rapport_score": scorecard.scores.rapport,
            "diagnosis_score": scorecard.scores.diagnosis,
            "objection_score": scorecard.scores.objection_handling,
            "close_score": scorecard.scores.close,
            "compliance_score": scorecard.scores.compliance,
            "overall_score": scorecard.scores.overall,
            "therapist_mode_flag": scorecard.therapist_mode_flag,
            "therapist_mode_reason": scorecard.therapist_mode_reason,
            "win_loss_timestamp": scorecard.win_loss_moment.timestamp_seconds,
            "win_loss_description": scorecard.win_loss_moment.description,
            "ai_summary": scorecard.ai_summary,
        }).execute()

        # ── Persist coaching moments ─────────────────────────────────────
        if scorecard.coaching_moments:
            db.table("coaching_moments").insert([
                {
                    "call_id": call_id,
                    "timestamp_seconds": m.timestamp_seconds,
                    "category": m.category.value,
                    "severity": m.severity.value,
                    "note": m.note,
                }
                for m in scorecard.coaching_moments
            ]).execute()

        # ── Persist objections ───────────────────────────────────────────
        if scorecard.objections:
            db.table("call_objections").insert([
                {
                    "call_id": call_id,
                    "timestamp_seconds": o.timestamp_seconds,
                    "objection_type": o.objection_type.value,
                    "objection_text": o.objection_text,
                    "handling_quality": o.handling_quality.value,
                }
                for o in scorecard.objections
            ]).execute()

        _update_call(call_id, status="scored")
        logger.info(
            "score_call complete: call_id=%s overall=%d",
            call_id,
            scorecard.scores.overall,
        )

        # ── Fire-and-forget Slack notification ───────────────────────────
        # Isolated as its own task so a Slack outage cannot corrupt a
        # successfully-scored call's status.
        try:
            notify_scorecard.delay(call_id)
        except Exception as notify_exc:
            logger.warning("Failed to enqueue notify_scorecard: %s", notify_exc)

        return {"call_id": call_id, "status": "scored", "overall": scorecard.scores.overall}

    except Exception as exc:
        logger.error("score_call failed: call_id=%s error=%s", call_id, exc, exc_info=True)
        _update_call(call_id, status="failed", error_message=str(exc)[:500])
        raise


# ── Task: notify_scorecard ───────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="notify_scorecard",
    max_retries=5,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
)
def notify_scorecard(self, call_id: str) -> dict:
    """Post a formatted scorecard to Slack (main message + threaded details).

    Reads from DB so this task is idempotent and replayable without side effects
    beyond a duplicate Slack post. Intentionally has no status transition —
    call.status remains 'scored' regardless of Slack outcome.
    """
    logger.info("notify_scorecard started: call_id=%s", call_id)
    db = get_supabase()

    # ── Load call + rep + scorecard + children ──────────────────────────
    call_resp = (
        db.table("calls")
        .select("*, reps(name), call_scores(*)")
        .eq("id", call_id)
        .single()
        .execute()
    )
    call = call_resp.data
    score_rows = call.get("call_scores") or []
    if not score_rows:
        logger.warning("notify_scorecard: no call_scores row for call_id=%s", call_id)
        return {"call_id": call_id, "status": "skipped", "reason": "no_scorecard"}
    score = score_rows[0] if isinstance(score_rows, list) else score_rows

    coaching = (
        db.table("coaching_moments")
        .select("*")
        .eq("call_id", call_id)
        .order("timestamp_seconds")
        .execute()
        .data
        or []
    )
    objections = (
        db.table("call_objections")
        .select("*")
        .eq("call_id", call_id)
        .order("timestamp_seconds")
        .execute()
        .data
        or []
    )

    rep_name = (call.get("reps") or {}).get("name", "Unknown rep")
    channel = settings.slack_scorecard_channel

    # ── Main scorecard message ───────────────────────────────────────────
    main_blocks = build_scorecard_blocks(
        rep_name=rep_name,
        lead_name=call.get("lead_name"),
        lead_source=call.get("lead_source"),
        outcome=call.get("outcome"),
        scores={
            "rapport": score["rapport_score"],
            "diagnosis": score["diagnosis_score"],
            "objection_handling": score["objection_score"],
            "close": score["close_score"],
            "compliance": score["compliance_score"],
        },
        overall_score=score["overall_score"],
        therapist_mode_flag=score["therapist_mode_flag"],
        therapist_mode_reason=score.get("therapist_mode_reason"),
        ai_summary=score["ai_summary"],
        win_loss_timestamp=score.get("win_loss_timestamp"),
        win_loss_description=score.get("win_loss_description"),
        recording_url=call.get("recording_url"),
    )
    fallback = build_fallback_text(rep_name, score["overall_score"], call.get("outcome"))

    thread_ts = post_message(channel=channel, blocks=main_blocks, text=fallback)
    logger.info("Posted main scorecard: call_id=%s ts=%s", call_id, thread_ts)

    # ── Threaded coaching moments (highest severity first) ──────────────
    severity_order = {"high": 0, "medium": 1, "low": 2}
    coaching_sorted = sorted(coaching, key=lambda m: severity_order.get(m["severity"], 3))

    for moment in coaching_sorted:
        blocks = build_coaching_moment_block(
            timestamp_seconds=moment["timestamp_seconds"],
            category=moment["category"],
            severity=moment["severity"],
            note=moment["note"],
        )
        try:
            post_message(
                channel=channel,
                blocks=blocks,
                text=moment["note"][:150],
                thread_ts=thread_ts,
            )
        except Exception as exc:
            # Don't fail the whole task over one thread reply
            logger.warning("Failed to post coaching moment: %s", exc)

    # ── Threaded objections summary (single reply) ──────────────────────
    if objections:
        obj_blocks = build_objections_summary_block(objections)
        try:
            post_message(
                channel=channel,
                blocks=obj_blocks,
                text=f"{len(objections)} objection(s) raised",
                thread_ts=thread_ts,
            )
        except Exception as exc:
            logger.warning("Failed to post objections summary: %s", exc)

    logger.info("notify_scorecard complete: call_id=%s", call_id)
    return {"call_id": call_id, "status": "notified", "thread_ts": thread_ts}


# ── Task: generate_weekly_report ─────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="generate_weekly_report",
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
)
def generate_weekly_report(self) -> dict:
    """Aggregate previous week's KPIs, snapshot to rep_kpi_snapshots,
    and post a formatted report to Slack.

    Triggered by Celery beat per WEEKLY_REPORT_DAY / WEEKLY_REPORT_HOUR.
    Idempotent: replaying on the same week upserts snapshots and reposts
    the Slack message (Slack itself doesn't dedupe — manual replay is
    always explicit and cheap).
    """
    logger.info("generate_weekly_report started")
    db = get_supabase()

    # ── Read pre-aggregated views ────────────────────────────────────────
    overview_resp = db.table("v_weekly_overview").select("*").execute()
    overview_rows = overview_resp.data or []
    overview = overview_rows[0] if overview_rows else {}

    rep_perf = (
        db.table("v_rep_performance_weekly").select("*").execute().data or []
    )
    top_objections = (
        db.table("v_top_objections_weekly").select("*").limit(10).execute().data or []
    )

    week_start = overview.get("week_start") or ""
    week_end = overview.get("week_end") or ""
    total_calls = overview.get("total_calls") or 0

    logger.info(
        "Weekly data loaded: week=%s→%s total_calls=%d reps=%d objections=%d",
        week_start, week_end, total_calls, len(rep_perf), len(top_objections),
    )

    # ── Upsert rep KPI snapshots (only if there's data) ─────────────────
    if total_calls > 0 and week_start:
        snapshot_rows = [
            {
                "rep_id": r["rep_id"],
                "snapshot_date": week_start,
                "period": "weekly",
                "total_calls": r.get("total_calls") or 0,
                "sold_calls": r.get("sold_calls") or 0,
                "close_rate": r.get("close_rate_pct"),
                "avg_overall_score": r.get("avg_overall_score"),
                "avg_rapport": r.get("avg_rapport"),
                "avg_diagnosis": r.get("avg_diagnosis"),
                "avg_objection": r.get("avg_objection"),
                "avg_close": r.get("avg_close"),
                "avg_compliance": r.get("avg_compliance"),
                "therapist_mode_count": r.get("therapist_mode_count") or 0,
            }
            for r in rep_perf
            if (r.get("total_calls") or 0) > 0
        ]
        if snapshot_rows:
            try:
                # UNIQUE (rep_id, snapshot_date, period) allows upsert
                db.table("rep_kpi_snapshots").upsert(
                    snapshot_rows,
                    on_conflict="rep_id,snapshot_date,period",
                ).execute()
                logger.info("Upserted %d KPI snapshots", len(snapshot_rows))
            except Exception as exc:
                # Don't let snapshot failures block the Slack post —
                # the report itself is the user-facing deliverable.
                logger.error("KPI snapshot upsert failed: %s", exc)

    # ── Build and post Slack report ─────────────────────────────────────
    blocks = build_weekly_report_blocks(
        week_start=week_start,
        week_end=week_end,
        overview=overview,
        rep_performance=rep_perf,
        top_objections=top_objections,
    )
    fallback = build_weekly_fallback_text(
        week_start=week_start,
        total_calls=total_calls,
        close_rate=overview.get("close_rate_pct"),
    )

    ts = post_message(
        channel=settings.slack_reports_channel,
        blocks=blocks,
        text=fallback,
    )
    logger.info("Weekly report posted: ts=%s", ts)

    return {
        "week_start": str(week_start),
        "total_calls": total_calls,
        "reps_reported": len(rep_perf),
        "ts": ts,
    }
