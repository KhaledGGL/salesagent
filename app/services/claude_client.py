"""Claude API client — transcript scoring.

Uses claude-sonnet-4-6 (Sonnet is cost-effective for structured extraction
tasks with well-defined rubrics; save Opus for deep-reasoning workloads).
"""

import json
import logging
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError

from app.core.prompts import SCORING_SYSTEM_PROMPT, SCORING_USER_PROMPT
from config import settings
from schemas import ScorecardOutput

logger = logging.getLogger(__name__)

SCORING_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048

_client: Anthropic | None = None


def get_anthropic() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


class TranscriptTooShortError(Exception):
    """Raised when Claude returns {\"error\": ...} — e.g. transcript too short."""


def score_transcript(
    *,
    transcript: str,
    rep_name: str,
    lead_name: str | None,
    lead_source: str | None,
    lead_temperature: str | None,
    call_type: str | None,
    outcome: str | None,
    duration_seconds: int | None,
) -> ScorecardOutput:
    """Send a transcript to Claude and return a validated ScorecardOutput.

    Raises:
        TranscriptTooShortError: Claude returned an {"error": ...} response.
        ValidationError: Claude's JSON didn't match the ScorecardOutput schema.
    """
    duration_minutes = round((duration_seconds or 0) / 60, 1)

    user_prompt = SCORING_USER_PROMPT.format(
        rep_name=rep_name or "Unknown",
        lead_name=lead_name or "Unknown",
        lead_source=lead_source or "unknown",
        lead_temperature=lead_temperature or "unknown",
        call_type=call_type or "discovery",
        outcome=outcome or "unknown",
        duration_minutes=duration_minutes,
        transcript=transcript,
    )

    client = get_anthropic()
    response = client.messages.create(
        model=SCORING_MODEL,
        max_tokens=MAX_TOKENS,
        system=SCORING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text").strip()
    logger.info("Claude returned %d chars for scoring", len(raw_text))

    # Strip accidental markdown fences if Claude ignored instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        # remove optional "json" tag on first line
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].lstrip()

    try:
        data: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON: %s", raw_text[:500])
        raise ValueError(f"Claude response was not valid JSON: {exc}") from exc

    # Transcript-too-short escape hatch per prompt spec
    if "error" in data and "scores" not in data:
        raise TranscriptTooShortError(data["error"])

    try:
        return ScorecardOutput(**data)
    except ValidationError:
        logger.error("Claude output failed ScorecardOutput validation: %s", raw_text[:500])
        raise
