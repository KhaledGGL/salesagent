"""Slack Block Kit builders for scorecard notifications.

Design:
- Main message: header + score grid + AI summary + therapist mode banner (if triggered)
- Thread replies: one per coaching moment (severity + category + note)
- Emoji/color signals let managers triage the channel at a glance.
"""

from typing import Any


# ── Emoji helpers ────────────────────────────────────────────────────────────

def _score_emoji(score: int) -> str:
    if score >= 8:
        return "🟢"
    if score >= 5:
        return "🟡"
    return "🔴"


def _severity_emoji(severity: str) -> str:
    return {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}.get(severity, "•")


def _outcome_emoji(outcome: str | None) -> str:
    return {
        "sold": "✅",
        "not_sold": "❌",
        "no_show": "👻",
        "rescheduled": "📅",
    }.get(outcome or "", "•")


def _fmt_seconds(seconds: int) -> str:
    """Render 125 → '2:05' for timestamp display."""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


# ── Main scorecard message ───────────────────────────────────────────────────

def build_scorecard_blocks(
    *,
    rep_name: str,
    lead_name: str | None,
    lead_source: str | None,
    outcome: str | None,
    scores: dict[str, int],
    overall_score: int,
    therapist_mode_flag: bool,
    therapist_mode_reason: str | None,
    ai_summary: str,
    win_loss_timestamp: int | None,
    win_loss_description: str | None,
    recording_url: str | None,
) -> list[dict[str, Any]]:
    """Compose the primary Block Kit message for a scored call."""
    overall_e = _score_emoji(overall_score)
    outcome_e = _outcome_emoji(outcome)

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{overall_e} {rep_name} — {overall_score}/10",
                "emoji": True,
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"*Lead:* {lead_name or '—'}   "
                        f"*Source:* {lead_source or '—'}   "
                        f"*Outcome:* {outcome_e} {outcome or '—'}"
                    ),
                }
            ],
        },
        {"type": "divider"},
    ]

    # ── Therapist mode banner ─────────────────────────────────────────────
    if therapist_mode_flag:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"🛑 *Therapist Mode Triggered*\n"
                    f"_{therapist_mode_reason or 'See coaching moments for details.'}_"
                ),
            },
        })
        blocks.append({"type": "divider"})

    # ── Score grid (2 columns) ────────────────────────────────────────────
    score_fields = [
        ("Rapport", scores["rapport"]),
        ("Diagnosis", scores["diagnosis"]),
        ("Objection", scores["objection_handling"]),
        ("Close", scores["close"]),
        ("Compliance", scores["compliance"]),
    ]
    blocks.append({
        "type": "section",
        "fields": [
            {
                "type": "mrkdwn",
                "text": f"*{label}*\n{_score_emoji(val)} {val}/10",
            }
            for label, val in score_fields
        ],
    })

    # ── AI summary ────────────────────────────────────────────────────────
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*Summary*\n{ai_summary}"},
    })

    # ── Win/loss moment ───────────────────────────────────────────────────
    if win_loss_description and win_loss_timestamp is not None:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*🎯 Key Moment ({_fmt_seconds(win_loss_timestamp)})*\n"
                    f"{win_loss_description}"
                ),
            },
        })

    # ── Recording link ────────────────────────────────────────────────────
    if recording_url:
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "▶ Listen to recording"},
                    "url": recording_url,
                    "style": "primary",
                }
            ],
        })

    return blocks


# ── Threaded coaching reply ──────────────────────────────────────────────────

def build_coaching_moment_block(
    *,
    timestamp_seconds: int,
    category: str,
    severity: str,
    note: str,
) -> list[dict[str, Any]]:
    """One coaching moment as a threaded reply block."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{_severity_emoji(severity)} *{category.replace('_', ' ').title()}* "
                    f"at `{_fmt_seconds(timestamp_seconds)}`\n{note}"
                ),
            },
        }
    ]


def build_objections_summary_block(objections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One threaded reply summarizing all objections raised in the call."""
    if not objections:
        return []
    lines = [
        f"• `{_fmt_seconds(o['timestamp_seconds'])}` *{o['objection_type']}* "
        f"({o['handling_quality']}) — _{o['objection_text']}_"
        for o in objections
    ]
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Objections raised*\n" + "\n".join(lines),
            },
        }
    ]


# ── Fallback plaintext for notification previews ─────────────────────────────

def build_fallback_text(rep_name: str, overall_score: int, outcome: str | None) -> str:
    return f"{rep_name} scored {overall_score}/10 — {outcome or 'outcome unknown'}"
