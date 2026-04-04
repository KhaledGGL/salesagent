"""GHL webhook receiver — signature verification → DB insert → Celery enqueue."""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.db import get_supabase
from config import settings
from schemas import GHLWebhookPayload

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Signature verification ───────────────────────────────────────────────────

def _verify_signature(payload_bytes: bytes, signature: str) -> bool:
    """HMAC-SHA256 verification of the incoming webhook body."""
    expected = hmac.new(
        settings.webhook_secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Webhook endpoint ─────────────────────────────────────────────────────────

@router.post("/ghl/call-completed", status_code=200)
async def ghl_call_completed(
    request: Request,
    x_ghl_signature: str = Header(alias="X-GHL-Signature", default=""),
):
    """Receive a call-completed webhook from GHL.

    Flow:
    1. Verify HMAC signature
    2. Parse payload into GHLWebhookPayload
    3. Upsert rep if unknown (auto-provision)
    4. Insert a `calls` row with status='received'
    5. Enqueue the Celery `process_call` task
    """
    body = await request.body()

    # 1. Signature check
    if settings.is_production and not _verify_signature(body, x_ghl_signature):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. Parse
    raw = await request.json()
    try:
        payload = GHLWebhookPayload(
            message_id=raw.get("messageId", raw.get("message_id", "")),
            conversation_id=raw.get("conversationId", raw.get("conversation_id", "")),
            contact_id=raw.get("contactId", raw.get("contact_id", "")),
            location_id=raw.get("locationId", raw.get("location_id", "")),
            user_id=raw.get("userId", raw.get("user_id", "")),
            duration_seconds=raw.get("duration"),
            called_at=raw.get("dateAdded") or raw.get("createdAt"),
        )
    except Exception as exc:
        logger.error("Payload parse error: %s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    db = get_supabase()

    # 3. Upsert rep (auto-provision with placeholder name)
    rep_row = (
        db.table("reps")
        .select("id")
        .eq("ghl_user_id", payload.user_id)
        .maybe_single()
        .execute()
    )
    if rep_row.data:
        rep_id = rep_row.data["id"]
    else:
        new_rep = (
            db.table("reps")
            .insert({"ghl_user_id": payload.user_id, "name": f"Rep {payload.user_id[:8]}"})
            .execute()
        )
        rep_id = new_rep.data[0]["id"]
        logger.info("Auto-provisioned rep %s for ghl_user_id=%s", rep_id, payload.user_id)

    # 4. Deduplicate on ghl_message_id, then insert
    existing = (
        db.table("calls")
        .select("id")
        .eq("ghl_message_id", payload.message_id)
        .maybe_single()
        .execute()
    )
    if existing.data:
        logger.info("Duplicate webhook for message_id=%s, skipping", payload.message_id)
        return {"status": "duplicate", "call_id": existing.data["id"]}

    call_row = (
        db.table("calls")
        .insert({
            "rep_id": rep_id,
            "ghl_contact_id": payload.contact_id,
            "ghl_message_id": payload.message_id,
            "ghl_conversation_id": payload.conversation_id,
            "duration_seconds": payload.duration_seconds,
            "called_at": payload.called_at,
            "status": "received",
        })
        .execute()
    )
    call_id = call_row.data[0]["id"]
    logger.info("Inserted call %s (message_id=%s)", call_id, payload.message_id)

    # 5. Enqueue Celery task
    from app.workers.tasks import process_call

    process_call.delay(call_id, payload.message_id)
    logger.info("Enqueued process_call for call_id=%s", call_id)

    return {"status": "accepted", "call_id": call_id}
