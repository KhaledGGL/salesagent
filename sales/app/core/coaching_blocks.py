"""Slack Block Kit builders for the weekly coaching lesson.

Pure functions — take Claude's CoachingLessonOutput and return Block Kit.
No DB access, trivially unit-testable.
"""

from typing import Any

from sales.app.core.slack_text import chunk_mrkdwn_section
from sales.schemas import CoachingLessonOutput


CATEGORY_EMOJI = {
    "rapport": "🤝",
    "diagnosis": "🔍",
    "objection_handling": "🛡️",
    "close": "🎯",
    "compliance": "📋",
}

CATEGORY_LABEL = {
    "rapport": "Rapport",
    "diagnosis": "Diagnosis",
    "objection_handling": "Objection Handling",
    "close": "Close",
    "compliance": "Compliance",
}


def build_coaching_lesson_blocks(
    *,
    week_start: str,
    week_end: str,
    lesson: CoachingLessonOutput,
) -> list[dict[str, Any]]:
    """Compose the full coaching lesson Block Kit message."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📚 Weekly Coaching Lesson — {week_start} → {week_end}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{lesson.headline}*",
            },
        },
        {"type": "divider"},
    ]

    for insight in lesson.category_insights:
        emoji = CATEGORY_EMOJI.get(insight.category, "📌")
        label = CATEGORY_LABEL.get(insight.category, insight.category.replace("_", " ").title())

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{label}*",
            },
        })

        if insight.best_examples:
            best_lines = [
                f"  • *{ex.rep_name}*: {ex.what_they_did} — _{ex.quote}_"
                for ex in insight.best_examples
            ]
            blocks.extend(chunk_mrkdwn_section("✅ *What went well:*", best_lines))

        if insight.worst_examples:
            worst_lines = [
                f"  • *{ex.rep_name}*: {ex.what_they_did} — _{ex.quote}_"
                for ex in insight.worst_examples
            ]
            blocks.extend(chunk_mrkdwn_section("❌ *What needs work:*", worst_lines))

        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"💡 *Advice:* {insight.advice}",
            }],
        })

        blocks.append({"type": "divider"})

    # Weekly focus callout
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"🎯 *This Week's Focus:* {lesson.weekly_focus}",
        },
    })

    return blocks


def build_coaching_fallback_text(week_start: str, total_calls: int) -> str:
    if total_calls == 0:
        return f"Coaching lesson ({week_start}): no calls"
    return f"Coaching lesson ({week_start}): {total_calls} calls analyzed"
