"""Celery tasks — call processing pipeline.

Pipeline:
    webhook → score_call → notify_scorecard

The webhook (/webhooks/ghl/transcript-ready) inserts the call row with
the transcript already populated and full UTM-based enrichment. There's
no transcript fetch to do, so process_call (the legacy task that handled
the GHL Conversations API round-trip) was deleted — webhook now enqueues
score_call directly.
"""

import logging
from typing import Any

from pydantic import ValidationError

from app.core.coaching_blocks import build_coaching_fallback_text, build_coaching_lesson_blocks
from app.core.marketing_blocks import build_marketing_fallback_text, build_marketing_intel_blocks
from app.core.report_blocks import build_weekly_fallback_text, build_weekly_report_blocks
from app.core.slack_blocks import (
    build_coaching_moment_block,
    build_fallback_text,
    build_objections_summary_block,
    build_scorecard_blocks,
)
from app.db import get_supabase
from app.services.claude_client import (
    TranscriptTooShortError,
    generate_coaching_lesson,
    generate_marketing_intel,
    score_transcript,
)
from app.services.slack_client import post_message
from app.workers.celery_app import celery_app
from config import settings
from schemas import ScorecardOutput

logger = logging.getLogger(__name__)


def _update_call(call_id: str, **fields) -> None:
    get_supabase().table("calls").update(fields).eq("id", call_id).execute()


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
            "outcome_confidence": scorecard.outcome_confidence,
            "outcome_evidence": scorecard.outcome_evidence,
        }).execute()

        # Write the AI-classified outcome onto the call row so the views
        # (which filter on calls.outcome = 'sold') count this correctly.
        db.table("calls").update({"outcome": scorecard.outcome}).eq("id", call_id).execute()

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
        outcome_confidence=score.get("outcome_confidence"),
        outcome_evidence=score.get("outcome_evidence"),
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
        recording_url=None,
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


# ── Helper: persist a generated weekly report ───────────────────────────────

def _persist_weekly_report(
    report_type: str,
    week_start: str | None,
    week_end: str | None,
    payload: dict[str, Any],
) -> None:
    """Idempotent upsert of a generated weekly report's JSON payload.

    Best-effort: a DB hiccup must NOT block Slack delivery, since the
    Slack post is the user-facing deliverable and the persistence is
    a UI-archive convenience. Mirrors the rep_kpi_snapshots pattern in
    generate_weekly_report.
    """
    if not week_start:
        return  # zero-call week with no boundary — nothing to anchor on
    try:
        get_supabase().table("weekly_reports").upsert(
            {
                "report_type": report_type,
                "week_start": str(week_start),
                "week_end": str(week_end or week_start),
                "payload": payload,
            },
            on_conflict="report_type,week_start",
        ).execute()
        logger.info("Persisted weekly_report type=%s week=%s", report_type, week_start)
    except Exception as exc:
        logger.error("weekly_reports upsert failed type=%s: %s", report_type, exc)


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

    # ── Persist for the UI archive ───────────────────────────────────────
    _persist_weekly_report(
        "sales",
        week_start,
        week_end,
        {
            "overview": overview,
            "rep_performance": rep_perf,
            "top_objections": top_objections,
        },
    )

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


# ── Task: generate_coaching_lesson ─────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="generate_coaching_lesson",
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
)
def generate_coaching_lesson_task(self) -> dict:
    """Pull the week's coaching moments, send to Claude for synthesis,
    and post a coaching lesson to Slack.

    Runs 5 minutes after the weekly report via Celery beat.
    """
    import json as _json

    logger.info("generate_coaching_lesson started")
    db = get_supabase()

    # ── Read data ───────────────────────────────────────────────────────
    overview_resp = db.table("v_weekly_overview").select("*").execute()
    overview_rows = overview_resp.data or []
    overview = overview_rows[0] if overview_rows else {}

    total_calls = overview.get("total_calls") or 0
    week_start = overview.get("week_start") or ""
    week_end = overview.get("week_end") or ""

    if total_calls == 0:
        logger.info("No calls last week — skipping coaching lesson")
        return {"week_start": str(week_start), "total_calls": 0, "status": "skipped"}

    moments = (
        db.table("v_weekly_coaching_moments").select("*").execute().data or []
    )

    if not moments:
        logger.info("No coaching moments last week — skipping coaching lesson")
        return {"week_start": str(week_start), "total_calls": total_calls, "status": "skipped"}

    # ── Group by category ───────────────────────────────────────────────
    by_category: dict[str, list[dict]] = {}
    for m in moments:
        cat = m.get("category", "other")
        by_category.setdefault(cat, []).append(m)

    moments_json = _json.dumps(by_category, indent=2, default=str)
    avg_score = overview.get("avg_overall_score") or 0

    # ── Call Claude ─────────────────────────────────────────────────────
    lesson = generate_coaching_lesson(
        coaching_moments_json=moments_json,
        week_start=str(week_start),
        week_end=str(week_end),
        total_calls=total_calls,
        avg_score=float(avg_score),
    )

    # ── Persist for the UI archive ───────────────────────────────────────
    _persist_weekly_report("coaching", str(week_start), str(week_end), lesson.model_dump())

    # ── Post to Slack ──────────────────────────────────────────────────
    blocks = build_coaching_lesson_blocks(
        week_start=str(week_start),
        week_end=str(week_end),
        lesson=lesson,
    )
    fallback = build_coaching_fallback_text(
        week_start=str(week_start),
        total_calls=total_calls,
    )

    ts = post_message(
        channel=settings.slack_reports_channel,
        blocks=blocks,
        text=fallback,
    )
    logger.info("Coaching lesson posted: ts=%s", ts)

    return {
        "week_start": str(week_start),
        "total_calls": total_calls,
        "categories": len(by_category),
        "ts": ts,
    }


# ── Task: generate_marketing_intel ─────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="generate_marketing_intel",
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
)
def generate_marketing_intel_task(self) -> dict:
    """Pull the week's sales data, send to Claude for marketing analysis,
    and post intelligence to Slack.

    Runs 10 minutes after the weekly report via Celery beat.
    """
    import json as _json

    logger.info("generate_marketing_intel started")
    db = get_supabase()

    # ── Read data ───────────────────────────────────────────────────────
    overview_resp = db.table("v_weekly_overview").select("*").execute()
    overview_rows = overview_resp.data or []
    overview = overview_rows[0] if overview_rows else {}

    total_calls = overview.get("total_calls") or 0
    week_start = overview.get("week_start") or ""
    week_end = overview.get("week_end") or ""

    if total_calls == 0:
        logger.info("No calls last week — skipping marketing intel")
        return {"week_start": str(week_start), "total_calls": 0, "status": "skipped"}

    # Objections with context
    objections = (
        db.table("v_top_objections_weekly").select("*").execute().data or []
    )

    # AI summaries
    summaries = (
        db.table("v_weekly_ai_summaries").select("*").execute().data or []
    )

    # Source performance
    source_perf = (
        db.table("v_weekly_source_performance").select("*").execute().data or []
    )

    if not objections and not summaries:
        logger.info("No objections or summaries last week — skipping marketing intel")
        return {"week_start": str(week_start), "total_calls": total_calls, "status": "skipped"}

    # ── Call Claude ─────────────────────────────────────────────────────
    intel = generate_marketing_intel(
        source_performance_json=_json.dumps(source_perf, indent=2, default=str),
        objections_json=_json.dumps(objections, indent=2, default=str),
        ai_summaries_json=_json.dumps(summaries, indent=2, default=str),
        week_start=str(week_start),
        week_end=str(week_end),
    )

    # ── Persist for the UI archive ───────────────────────────────────────
    _persist_weekly_report("marketing", str(week_start), str(week_end), intel.model_dump())

    # ── Post to Slack ──────────────────────────────────────────────────
    blocks = build_marketing_intel_blocks(
        week_start=str(week_start),
        week_end=str(week_end),
        intel=intel,
    )
    fallback = build_marketing_fallback_text(
        week_start=str(week_start),
        total_calls=total_calls,
    )

    ts = post_message(
        channel=settings.slack_marketing_channel,
        blocks=blocks,
        text=fallback,
    )
    logger.info("Marketing intel posted: ts=%s", ts)

    return {
        "week_start": str(week_start),
        "total_calls": total_calls,
        "objections": len(objections),
        "summaries": len(summaries),
        "ts": ts,
    }
