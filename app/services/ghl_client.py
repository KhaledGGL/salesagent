"""GoHighLevel API client — 2-step transcript fetch.

Step 1: GET /conversations/messages/{messageId}  → recording URL
Step 2: GET recording URL or fetch transcript body from the message
"""

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

GHL_BASE = "https://services.leadconnectorhq.com"
TIMEOUT = 30.0


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.ghl_api_key}",
        "Version": "2021-07-28",
        "Accept": "application/json",
    }


# ── Step 1: fetch message details ────────────────────────────────────────────

def get_message(message_id: str) -> dict[str, Any]:
    """Return the full message object from GHL Conversations API."""
    url = f"{GHL_BASE}/conversations/messages/{message_id}"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


# ── Step 2: fetch transcript / recording ──────────────────────────────────────

def fetch_transcript(message_id: str) -> dict[str, Any]:
    """Two-step fetch: get message → extract recording URL → download transcript.

    Returns:
        {
            "transcript": str | None,
            "recording_url": str | None,
            "duration_seconds": int | None,
            "called_at": str | None,
        }
    """
    msg = get_message(message_id)
    logger.info("GHL message %s fetched, keys: %s", message_id, list(msg.keys()))

    # GHL nests call data under "message" or at top level depending on version
    body = msg.get("message", msg)

    recording_url: str | None = (
        body.get("attachments", [{}])[0].get("url")
        if body.get("attachments")
        else body.get("recordingUrl")
    )

    transcript_text: str | None = body.get("transcript") or body.get("transcription")
    duration: int | None = body.get("duration") or body.get("callDuration")
    called_at: str | None = body.get("dateAdded") or body.get("createdAt")

    # If we have a recording URL but no transcript, attempt to fetch the
    # transcript from the recording endpoint (some GHL setups store it there).
    if recording_url and not transcript_text:
        transcript_text = _fetch_transcript_from_recording(recording_url)

    return {
        "transcript": transcript_text,
        "recording_url": recording_url,
        "duration_seconds": int(duration) if duration else None,
        "called_at": called_at,
    }


def _fetch_transcript_from_recording(recording_url: str) -> str | None:
    """Best-effort download of a transcript linked to a recording URL."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.get(recording_url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
            return data.get("transcript") or data.get("transcription")
    except Exception:
        logger.warning("Could not fetch transcript from recording URL: %s", recording_url, exc_info=True)
        return None


# ── Contact fetch (lead enrichment) ───────────────────────────────────────────

def get_contact(contact_id: str) -> dict[str, Any]:
    """Fetch a contact record from GHL for lead enrichment."""
    url = f"{GHL_BASE}/contacts/{contact_id}"
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        # GHL wraps under "contact" in some API versions
        return data.get("contact", data)


# ── Source normalization ─────────────────────────────────────────────────────

_META_TOKENS = {"facebook", "fb", "instagram", "ig", "meta"}
_GOOGLE_TOKENS = {"google", "goog", "adwords", "youtube", "yt"}


def map_ghl_source(ghl_source: str) -> str:
    """Normalize GHL's freeform source values to our lead_source enum.

    Tokenizes on non-alphanumerics and matches whole tokens only. Substring
    matching caused misclassifications (e.g. "campaign" contained "ig" and
    was tagged as Meta). Whole-token matching is the correct semantics.
    """
    import re

    tokens = set(re.findall(r"[a-z0-9]+", (ghl_source or "").lower()))
    if tokens & _META_TOKENS:
        return "meta"
    if tokens & _GOOGLE_TOKENS:
        return "google"
    return "organic"
