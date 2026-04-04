"""Celery tasks — call processing pipeline."""

import logging

from app.db import get_supabase
from app.services.ghl_client import fetch_transcript
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _update_call(call_id: str, **fields) -> None:
    get_supabase().table("calls").update(fields).eq("id", call_id).execute()


@celery_app.task(
    bind=True,
    name="process_call",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_call(self, call_id: str, message_id: str) -> dict:
    """Fetch transcript from GHL, persist it, then enqueue scoring.

    Status transitions: received → fetching → queued  (→ scoring happens later)
    On failure:         any → failed
    """
    logger.info("process_call started: call_id=%s message_id=%s", call_id, message_id)

    try:
        # ── Step 1: Mark as fetching ─────────────────────────────────────
        _update_call(call_id, status="fetching")

        # ── Step 2: 2-step transcript fetch from GHL ─────────────────────
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

        # ── Step 3: Persist transcript + metadata ────────────────────────
        update_fields = {
            "transcript": transcript,
            "status": "queued",
        }
        if result["recording_url"]:
            update_fields["recording_url"] = result["recording_url"]
        if result["duration_seconds"]:
            update_fields["duration_seconds"] = result["duration_seconds"]
        if result["called_at"]:
            update_fields["called_at"] = result["called_at"]

        _update_call(call_id, **update_fields)
        logger.info("Transcript saved for call_id=%s, status → queued", call_id)

        # ── Step 4: Enqueue scoring task (placeholder for Step 6) ────────
        # score_call.delay(call_id)   # uncomment when scoring task exists

        return {"call_id": call_id, "status": "queued"}

    except Exception as exc:
        logger.error("process_call failed: call_id=%s error=%s", call_id, exc, exc_info=True)
        _update_call(call_id, status="failed", error_message=str(exc)[:500])
        raise
