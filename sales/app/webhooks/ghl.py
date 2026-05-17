"""GHL webhook receiver — inline-transcript ingestion.

The /webhooks/ghl/transcript-ready endpoint is the sole ingestion model:
GHL's "Transcript Generated" workflow trigger POSTs the transcript
inline plus UTM merge tags for attribution. We persist the call with
full lead enrichment (UTM source/medium/campaign/content/term, plus
cold/warm computed from our own call history for this contact) and
dispatch scoring directly — no follow-up GHL Contacts API call.

This is a deliberate simplification of the original two-endpoint flow
(/call-completed → fetch_transcript via GHL API) because:

  1. Inline payload eliminates a round-trip and a race condition
     between "call ended" and "transcription ready" events.
  2. UTM-based attribution is more granular than the old 3-bucket
     contact source field — campaign / creative / keyword level.
  3. New clients no longer need a GHL Private Integration token,
     simplifying onboarding.
  4. Lead temperature computed from our own DB is more accurate than
     reading GHL's contact dateAdded (catches returning leads who
     re-enter after months of inactivity).
"""

import hashlib
import hmac
import json as _json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request

from core.db import get_supabase
from core.config import settings
from sales.schemas import GHLTranscriptReadyPayload

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


# ── UTM source → lead_source enum normalization ──────────────────────────────

def _normalize_utm_source(utm_source: str | None) -> str | None:
    """Map a free-form utm_source value to the LeadSource enum.

    Real-world utm_source values are messy ('facebook', 'fb', 'meta-cpc',
    'google-ads', 'organic', 'direct', etc.). We normalize the common ones
    so the existing analytical views (close rate by source, cold/warm
    comparison, etc.) keep working without expanding the enum surface.

    The full utm_* set is preserved on dedicated columns for
    campaign/creative-level analysis — this is just for the high-level bucket.
    """
    if not utm_source:
        return None
    s = utm_source.strip().lower()
    if not s:
        return None
    if "facebook" in s or "instagram" in s or "meta" in s or s in ("fb", "ig"):
        return "meta"
    if "google" in s or "adwords" in s or "youtube" in s or s == "g-ads":
        return "google"
    return "organic"


# ── Lead temperature from our own call history ───────────────────────────────

def _compute_lead_temperature(db, contact_id: str | None) -> str:
    """Cold if this is the first time we've seen this contact, warm otherwise.

    Replaces the legacy logic that read the GHL contact's dateAdded.
    Self-contained, more accurate (catches returning leads), and avoids
    the cross-system call. NULL contact_id falls back to 'cold'.
    """
    if not contact_id:
        return "cold"
    prior = (
        db.table("calls")
        .select("id")
        .eq("ghl_contact_id", contact_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return "warm" if prior else "cold"


# ── Webhook endpoint ─────────────────────────────────────────────────────────

@router.post("/ghl/transcript-ready", status_code=200)
async def ghl_transcript_ready(
    request: Request,
    x_ghl_signature: str = Header(alias="X-GHL-Signature", default=""),
):
    """Receive a transcript-generated webhook from GHL with inline transcript.

    Flow:
      1. Verify HMAC signature (production only)
      2. Parse + validate payload (tolerant of GHL's three body shapes)
      3. Filter out non-completed calls and too-short transcripts
      4. Upsert rep, dedup on call_sid
      5. Compute lead_temperature from our DB, normalize utm_source
      6. Insert call row with transcript + full UTM enrichment
      7. Enqueue score_call directly
    """
    body = await request.body()
    content_type = request.headers.get("content-type", "")

    # 1. Signature check (dev mode bypasses)
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
            def _escape_transcript(match: "re.Match") -> str:
                inner = match.group(1)
                inner = inner.replace("\\", "\\\\")
                inner = inner.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
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

    # 2c. Form-urlencoded fallback
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

    # 2e. Some GHL setups wrap everything inside a single "payload" field
    # whose value is a JSON string. Detect and unwrap.
    if len(raw) == 1 and "payload" in raw and isinstance(raw["payload"], str):
        try:
            inner = _json.loads(raw["payload"])
            if isinstance(inner, dict):
                raw = inner
        except Exception:
            pass  # leave raw as-is, validation will catch it

    # 2f. Coerce GHL's empty-string merge-tag defaults to None
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

    # 4a. Upsert rep — backfill placeholder names on existing rows when a
    # real call_user_name now arrives.
    placeholder_name = f"Rep {payload.call_user_id[:8]}"
    real_name = (payload.call_user_name or "").strip() or None

    rep_row = (
        db.table("reps")
        .select("id, name")
        .eq("ghl_user_id", payload.call_user_id)
        .maybe_single()
        .execute()
    )
    if rep_row is not None and rep_row.data:
        rep_id = rep_row.data["id"]
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

    # 5. Enrichment derived from this payload + our DB
    lead_source = _normalize_utm_source(payload.utm_source)
    lead_temperature = _compute_lead_temperature(db, payload.contact_id)

    # 6. Insert call row with full enrichment
    call_row = (
        db.table("calls")
        .insert({
            "rep_id":           rep_id,
            "ghl_contact_id":   payload.contact_id,
            "ghl_message_id":   payload.call_sid,
            "lead_name":        payload.contact_name,
            "lead_source":      lead_source,
            "lead_temperature": lead_temperature,
            "transcript":       transcript,
            "duration_seconds": payload.call_duration,
            "called_at":        datetime.now(timezone.utc).isoformat(),
            "status":           "received",
            "utm_source":       payload.utm_source,
            "utm_medium":       payload.utm_medium,
            "utm_campaign":     payload.utm_campaign,
            "utm_content":      payload.utm_content,
            "utm_term":         payload.utm_term,
        })
        .execute()
    )
    call_id = call_row.data[0]["id"]
    logger.info(
        "Inserted call %s (chars=%d sid=%s utm_source=%r → %s, temp=%s)",
        call_id, len(transcript), payload.call_sid,
        payload.utm_source, lead_source, lead_temperature,
    )

    # 7. Enqueue scoring directly — process_call is no longer needed since
    # there's no transcript fetch to do. score_call already handles its own
    # status transition (received → scoring → scored/failed).
    from sales.app.workers.tasks import score_call

    score_call.delay(call_id)
    logger.info("Enqueued score_call for call_id=%s", call_id)

    return {"status": "accepted", "call_id": call_id}
