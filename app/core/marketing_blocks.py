"""Slack Block Kit builders for the weekly marketing intelligence report.

Pure functions — take Claude's MarketingIntelOutput and return Block Kit.
No DB access, trivially unit-testable.
"""

from typing import Any

from schemas import MarketingIntelOutput


def build_marketing_intel_blocks(
    *,
    week_start: str,
    week_end: str,
    intel: MarketingIntelOutput,
) -> list[dict[str, Any]]:
    """Compose the full marketing intelligence Block Kit message."""
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📈 Weekly Marketing Intelligence — {week_start} → {week_end}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{intel.headline}*",
            },
        },
        {"type": "divider"},
    ]

    # ── Messaging Angles ────────────────────────────────────────────────
    if intel.messaging_angles:
        angle_lines = []
        for angle in intel.messaging_angles:
            quotes = ", ".join(f'"{q}"' for q in angle.example_quotes[:2])
            angle_lines.append(
                f"• *{angle.pain_point}* ({angle.frequency}x) — {quotes}"
            )
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🎤 Top Messaging Angles*\n" + "\n".join(angle_lines),
            },
        })
        blocks.append({"type": "divider"})

    # ── Source Analysis ─────────────────────────────────────────────────
    if intel.source_analysis:
        source_lines = []
        for src in intel.source_analysis:
            rate = f"{src.close_rate:.1f}%" if src.close_rate is not None else "—"
            source_lines.append(
                f"• *{src.source}* — {rate} close rate | {src.quality_assessment}\n"
                f"   → _{src.recommendation}_"
            )
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📊 Lead Source Quality*\n" + "\n".join(source_lines),
            },
        })
        blocks.append({"type": "divider"})

    # ── Pre-qualification Recommendations ──────────────────────────────
    if intel.prequalification_recs:
        prequal_lines = []
        for i, rec in enumerate(intel.prequalification_recs, 1):
            prequal_lines.append(f"{i}. *{rec.recommendation}*\n   _{rec.rationale}_")
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🎯 Pre-Qualification Recommendations*\n" + "\n".join(prequal_lines),
            },
        })
        blocks.append({"type": "divider"})

    # ── Positioning Gaps ───────────────────────────────────────────────
    if intel.positioning_gaps:
        gap_lines = []
        for gap in intel.positioning_gaps:
            gap_lines.append(
                f"• *{gap.gap}*\n"
                f"   Evidence: _{gap.evidence}_\n"
                f"   → _{gap.recommendation}_"
            )
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*⚠️ Positioning Gaps*\n" + "\n".join(gap_lines),
            },
        })

    return blocks


def build_marketing_fallback_text(week_start: str, total_calls: int) -> str:
    if total_calls == 0:
        return f"Marketing intelligence ({week_start}): no calls"
    return f"Marketing intelligence ({week_start}): {total_calls} calls analyzed"
