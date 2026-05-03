"""Claude API client — transcript scoring.

Uses claude-sonnet-4-6 (Sonnet is cost-effective for structured extraction
tasks with well-defined rubrics; save Opus for deep-reasoning workloads).
"""

import json
import logging
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError

from app.core.prompts import (
    COACHING_LESSON_SYSTEM_PROMPT,
    COACHING_LESSON_USER_PROMPT,
    MARKETING_INTEL_SYSTEM_PROMPT,
    MARKETING_INTEL_USER_PROMPT,
    SCORING_SYSTEM_PROMPT,
    SCORING_USER_PROMPT,
)
from config import settings
from schemas import CoachingLessonOutput, MarketingIntelOutput, ScorecardOutput

logger = logging.getLogger(__name__)

SCORING_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048

_client: Anthropic | None = None


def get_anthropic() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def _business_context_section() -> str:
    """Build the optional business context block for prompts."""
    ctx = settings.business_context.strip()
    if not ctx:
        return ""
    return f"\n## Business Information\n{ctx}\n"


class TranscriptTooShortError(Exception):
    """Raised when Claude returns {\"error\": ...} — e.g. transcript too short."""


def score_transcript(
    *,
    transcript: str,
    rep_name: str,
    lead_name: str | None,
    lead_source: str | None,
    lead_temperature: str | None,
    duration_seconds: int | None,
) -> ScorecardOutput:
    """Send a transcript to Claude and return a validated ScorecardOutput.

    The outcome (sold / not_sold / follow_up) is detected by Claude from
    the transcript itself — we deliberately do NOT pass any CRM-derived
    outcome hint, since reps update CRM fields after the call (often
    after scoring runs) and the resulting bias was undercounting closes.

    Raises:
        TranscriptTooShortError: Claude returned an {"error": ...} response.
        ValidationError: Claude's JSON didn't match the ScorecardOutput schema.
    """
    duration_minutes = round((duration_seconds or 0) / 60, 1)

    user_prompt = SCORING_USER_PROMPT.format(
        business_context_section=_business_context_section(),
        rep_name=rep_name or "Unknown",
        lead_name=lead_name or "Unknown",
        lead_source=lead_source or "unknown",
        lead_temperature=lead_temperature or "unknown",
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


ANALYSIS_MAX_TOKENS = 4096


def _call_claude_json(system_prompt: str, user_prompt: str, label: str) -> dict[str, Any]:
    """Shared helper: call Claude, parse JSON response, return raw dict."""
    client = get_anthropic()
    response = client.messages.create(
        model=SCORING_MODEL,
        max_tokens=ANALYSIS_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text").strip()
    logger.info("Claude returned %d chars for %s", len(raw_text), label)

    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:].lstrip()

    try:
        data: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("%s: Claude returned invalid JSON: %s", label, raw_text[:500])
        raise ValueError(f"{label}: Claude response was not valid JSON: {exc}") from exc

    return data


def generate_coaching_lesson(
    *,
    coaching_moments_json: str,
    week_start: str,
    week_end: str,
    total_calls: int,
    avg_score: float,
) -> CoachingLessonOutput:
    """Send aggregated coaching moments to Claude and return a coaching lesson."""
    user_prompt = COACHING_LESSON_USER_PROMPT.format(
        business_context_section=_business_context_section(),
        week_start=week_start,
        week_end=week_end,
        total_calls=total_calls,
        avg_score=avg_score,
        coaching_moments_json=coaching_moments_json,
    )

    data = _call_claude_json(COACHING_LESSON_SYSTEM_PROMPT, user_prompt, "coaching_lesson")

    try:
        return CoachingLessonOutput(**data)
    except ValidationError:
        logger.error("COACHING_DRIFT: Claude output failed CoachingLessonOutput validation: %s", str(data)[:500])
        raise


def generate_marketing_intel(
    *,
    source_performance_json: str,
    objections_json: str,
    ai_summaries_json: str,
    week_start: str,
    week_end: str,
) -> MarketingIntelOutput:
    """Send aggregated sales data to Claude and return marketing intelligence."""
    user_prompt = MARKETING_INTEL_USER_PROMPT.format(
        business_context_section=_business_context_section(),
        week_start=week_start,
        week_end=week_end,
        source_performance_json=source_performance_json,
        objections_json=objections_json,
        ai_summaries_json=ai_summaries_json,
    )

    data = _call_claude_json(MARKETING_INTEL_SYSTEM_PROMPT, user_prompt, "marketing_intel")

    try:
        return MarketingIntelOutput(**data)
    except ValidationError:
        logger.error("MARKETING_DRIFT: Claude output failed MarketingIntelOutput validation: %s", str(data)[:500])
        raise
