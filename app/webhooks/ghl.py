"""GHL webhook receiver — signature verification → DB insert → Celery enqueue."""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request

from app.db import get_supabase
from config import settings
from schemas import GHLTranscriptReadyPayload, GHLWebhookPayload

MIN_TRANSCRIPT_CHARS = 50  # below this, scoring is meaningless — drop early

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
    # supabase-py 2.28+ returns None directly from maybe_single().execute()
    # when no row matches, instead of an APIResponse with data=None.
    if rep_row is not None and rep_row.data:
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
    if existing is not None and existing.data:
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


# ── Inline-transcript webhook ────────────────────────────────────────────────
#
# GHL's "Transcript Generated" trigger fires AFTER transcription completes
# and lets us include the transcript text directly in the webhook body. This
# is preferable to /ghl/call-completed because:
#
#   1. No follow-up GHL API call needed → one less point of failure
#   2. No race between "call ended" and "transcription ready" events
#   3. Works on GHL workspaces where transcripts aren't exposed via the
#      Conversations API but ARE available in workflow merge tags
#
# This endpoint inserts the call with the transcript already populated, then
# dispatches process_call (which detects the inline transcript and skips the
# GHL fetch step, going straight to contact enrichment and scoring).

@router.post("/ghl/transcript-ready", status_code=200)
async def ghl_transcript_ready(
    request: Request,
    x_ghl_signature: str = Header(alias="X-GHL-Signature", default=""),
):
    """Receive a transcript-generated webhook from GHL with inline transcript.

    Flow:
    1. Verify HMAC signature (production only)
    2. Parse + validate payload
    3. Filter out non-completed calls and too-short transcripts
    4. Upsert rep, dedup on call_sid, insert call row WITH transcript
    5. Enqueue process_call (which will skip the GHL fetch step)
    """
    import json as _json
    from urllib.parse import parse_qs

    body = await request.body()
    content_type = request.headers.get("content-type", "")

    # 1. Signature check (dev mode bypasses, same as call-completed)
    if settings.is_production and not _verify_signature(body, x_ghl_signature):
        logger.warning("Invalid webhook signature on transcript-ready")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 2. Parse the body. GHL workflow webhooks ship payloads in several
    # shapes depending on version: pure JSON, form-urlencoded, JSON wrapped
    # inside a "payload" form field, or — most painfully — JSON-shaped text
    # where the transcript value contains unescaped newlines or quotes that
    # break strict JSON parsing. We try strict, then a tolerant repair, then
    # form, then fail loudly with the raw body in the logs.
    raw: dict | None = None
    parse_attempts: list[str] = []
    body_text = body.decode("utf-8", errors="replace")

    # 2a. Strict JSON
    try:
        candidate = _json.loads(body_text)
        if isinstance(candidate, dict):
            raw = candidate
            parse_attempts.append("json:ok")
        else:
            parse_attempts.append(f"json:not_object({type(candidate).__name__})")
    except Exception as exc:
        parse_attempts.append(f"json:fail({exc})")

    # 2b. Tolerant JSON repair — handle the common GHL failure mode where
    # the transcript value contains raw newlines / unescaped quotes that
    # strict JSON rejects. Strategy: pull out the transcript field by
    # regex, escape its contents, then re-parse.
    if raw is None and body_text.lstrip().startswith("{"):
        try:
            import re
            # Escape unescaped control chars inside the call_transcript value.
            # We greedy-match from `"call_transcript":"` to the next `"` that
            # is followed by either `,` or `}` (the end of the field).
            def _escape_transcript(match: "re.Match") -> str:
                inner = match.group(1)
                inner = inner.replace("\\", "\\\\")
                inner = inner.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
                # Escape any double-quote that isn't already escaped
                inner = re.sub(r'(?<!\\)"', r'\\"', inner)
                return f'"call_transcript": "{inner}"'

            repaired = re.sub(
                r'"call_transcript"\s*:\s*"(.*?)"(\s*[,}])',
                lambda m: _escape_transcript(m) + m.group(2),
                body_text,
                count=1,
                flags=re.DOTALL,
            )
            candidate = _json.loads(repaired)
            if isinstance(candidate, dict):
                raw = candidate
                parse_attempts.append("json_repair:ok")
        except Exception as exc:
            parse_attempts.append(f"json_repair:fail({exc})")

    # 2c. Form-urlencoded fallback. Reject single-key results where the key
    # itself looks like JSON (i.e. the form parser ate a JSON body whole).
    if raw is None:
        try:
            parsed = parse_qs(body_text, keep_blank_values=True)
            flat = {k: (v[0] if len(v) == 1 else v) for k, v in parsed.items()}
            if flat and not (len(flat) == 1 and any(c in next(iter(flat)) for c in '{"[')):
                raw = flat
                parse_attempts.append("form:ok")
            else:
                parse_attempts.append(f"form:nonsense_keys({list(flat)[:1]!r})")
        except Exception as exc:
            parse_attempts.append(f"form:fail({exc})")

    # 2d. If everything failed, log the raw body so we can see exactly what
    # GHL sent and either teach the parser a new shape or fix the workflow.
    if raw is None or not isinstance(raw, dict) or not raw:
        logger.error(
            "transcript-ready: could not parse body. content-type=%r len=%d attempts=%s preview=%r",
            content_type, len(body), parse_attempts, body_text[:1000],
        )
        raise HTTPException(
            status_code=422,
            detail=f"Unparseable body. content-type={content_type!r}. attempts={parse_attempts}",
        )

    # 2d. Some GHL setups wrap everything inside a single "payload" field
    # whose value is a JSON string. Detect and unwrap.
    if len(raw) == 1 and "payload" in raw and isinstance(raw["payload"], str):
        try:
            inner = _json.loads(raw["payload"])
            if isinstance(inner, dict):
                raw = inner
        except Exception:
            pass  # leave raw as-is, validation will catch it

    # 2e. Coerce GHL's empty-string merge-tag defaults to None
    raw = {k: (None if v == "" else v) for k, v in raw.items()}

    logger.info("transcript-ready parsed body: keys=%s", sorted(raw.keys()))

    try:
        payload = GHLTranscriptReadyPayload(**raw)
    except Exception as exc:
        logger.error(
            "transcript-ready payload validation error: %s | received_keys=%s",
            exc, sorted(raw.keys()),
        )
        raise HTTPException(status_code=422, detail=str(exc))

    # 3a. Filter: only score completed calls. Voicemails, no-answers, etc.
    # produce noise transcripts and pollute scoring averages.
    if payload.call_status and payload.call_status.lower() != "completed":
        logger.info(
            "Skipping non-completed call: sid=%s status=%s",
            payload.call_sid, payload.call_status,
        )
        return {"status": "skipped", "reason": f"call_status={payload.call_status}"}

    # 3b. Filter: drop too-short transcripts before they hit Claude
    transcript = payload.call_transcript.strip()
    if len(transcript) < MIN_TRANSCRIPT_CHARS:
        logger.info(
            "Skipping short transcript: sid=%s chars=%d",
            payload.call_sid, len(transcript),
        )
        return {"status": "skipped", "reason": "transcript_too_short"}

    db = get_supabase()

    # 4a. Upsert rep — auto-provision new reps; backfill placeholder names
    # on existing rows when a real call_user_name now arrives.
    placeholder_name = f"Rep {payload.call_user_id[:8]}"
    real_name = (payload.call_user_name or "").strip() or None

    rep_row = (
        db.table("reps")
        .select("id, name")
        .eq("ghl_user_id", payload.call_user_id)
        .maybe_single()
        .execute()
    )
    # supabase-py 2.28+ returns None directly when no row matches.
    if rep_row is not None and rep_row.data:
        rep_id = rep_row.data["id"]
        # Backfill: if the stored name is still our auto-provisioned placeholder
        # and we now have a real name, upgrade it. Don't touch human-edited names.
        if real_name and rep_row.data.get("name") == placeholder_name:
            db.table("reps").update({"name": real_name}).eq("id", rep_id).execute()
            logger.info("Backfilled rep %s name → %r", rep_id, real_name)
    else:
        new_rep = (
            db.table("reps")
            .insert({
                "ghl_user_id": payload.call_user_id,
                "name": real_name or placeholder_name,
            })
            .execute()
        )
        rep_id = new_rep.data[0]["id"]
        logger.info(
            "Auto-provisioned rep %s for ghl_user_id=%s name=%r",
            rep_id, payload.call_user_id, real_name or placeholder_name,
        )

    # 4b. Dedup on call_sid (Twilio SID is globally unique per call)
    existing = (
        db.table("calls")
        .select("id")
        .eq("ghl_message_id", payload.call_sid)
        .maybe_single()
        .execute()
    )
    if existing is not None and existing.data:
        logger.info("Duplicate transcript-ready for call_sid=%s, skipping", payload.call_sid)
        return {"status": "duplicate", "call_id": existing.data["id"]}

    # 4c. Insert call row WITH transcript already populated
    call_row = (
        db.table("calls")
        .insert({
            "rep_id": rep_id,
            "ghl_contact_id": payload.contact_id,
            "ghl_message_id": payload.call_sid,
            "lead_name": payload.contact_name,
            "transcript": transcript,
            "duration_seconds": payload.call_duration,
            "called_at": datetime.now(timezone.utc).isoformat(),
            "status": "received",
        })
        .execute()
    )
    call_id = call_row.data[0]["id"]
    logger.info(
        "Inserted call %s with inline transcript (%d chars, sid=%s)",
        call_id, len(transcript), payload.call_sid,
    )

    # 5. Enqueue process_call — it will detect the inline transcript and
    # skip the GHL fetch, doing only contact enrichment + score dispatch.
    from app.workers.tasks import process_call

    process_call.delay(call_id, payload.call_sid)
    logger.info("Enqueued process_call for inline-transcript call_id=%s", call_id)

    return {"status": "accepted", "call_id": call_id}
