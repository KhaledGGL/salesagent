"""Slack Block Kit builders for the weekly sales report.

Pure functions — take pre-aggregated data (from SQL views) and
return Block Kit. No DB access here, so they're trivially unit-testable.
"""

from typing import Any

TOP_N = 3  # how many reps / objections to surface per bucket


# ── Emoji / formatting helpers ───────────────────────────────────────────────

def _score_emoji(score: float | None) -> str:
    if score is None:
        return "•"
    if score >= 8:
        return "🟢"
    if score >= 5:
        return "🟡"
    return "🔴"


def _pct(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "—"


def _num(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}" if decimals else str(int(value))


# ── Main weekly report builder ───────────────────────────────────────────────

def build_weekly_report_blocks(
    *,
    week_start: str,
    week_end: str,
    overview: dict[str, Any],
    rep_performance: list[dict[str, Any]],
    top_objections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compose the full weekly report Block Kit message.

    Args:
        week_start / week_end: ISO date strings (YYYY-MM-DD)
        overview: org-wide totals dict (from v_weekly_overview)
        rep_performance: list of per-rep dicts (from v_rep_performance_weekly)
        top_objections: list of objection dicts (from v_top_objections_weekly)
    """
    total_calls = overview.get("total_calls") or 0

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📊 Weekly Sales Report — {week_start} → {week_end}",
                "emoji": True,
            },
        }
    ]

    # ── Empty-week short-circuit ─────────────────────────────────────────
    if total_calls == 0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "_No scored calls this week — nothing to report._",
            },
        })
        return blocks

    # ── Overview ─────────────────────────────────────────────────────────
    sold = overview.get("sold_calls") or 0
    close_rate = overview.get("close_rate_pct")
    avg_score = overview.get("avg_overall_score")
    therapist_count = overview.get("therapist_mode_count") or 0

    blocks.append({
        "type": "section",
        "fields": [
            {"type": "mrkdwn", "text": f"*📞 Total Calls*\n{total_calls}"},
            {"type": "mrkdwn", "text": f"*✅ Sold*\n{sold}"},
            {"type": "mrkdwn", "text": f"*📈 Close Rate*\n{_pct(close_rate)}"},
            {
                "type": "mrkdwn",
                "text": f"*🎯 Avg Score*\n{_score_emoji(avg_score)} {_num(avg_score, 2)}",
            },
        ],
    })

    if therapist_count:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"🛑 *Therapist mode triggered {therapist_count} time(s) this week*",
            }],
        })

    blocks.append({"type": "divider"})

    # ── Top performers (by close rate among reps with ≥3 calls) ─────────
    eligible = [r for r in rep_performance if (r.get("total_calls") or 0) >= 3]

    top_by_close = sorted(
        eligible,
        key=lambda r: (r.get("close_rate_pct") or 0),
        reverse=True,
    )[:TOP_N]

    if top_by_close:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🏆 Top Performers*\n" + "\n".join(
                    f"{i+1}. *{r['rep_name']}* — {_pct(r.get('close_rate_pct'))} "
                    f"close rate ({r['total_calls']} calls, "
                    f"{_score_emoji(r.get('avg_overall_score'))} {_num(r.get('avg_overall_score'), 1)} avg)"
                    for i, r in enumerate(top_by_close)
                ),
            },
        })

    # ── Reps needing coaching (by lowest avg score, ≥3 calls) ───────────
    needs_coaching = sorted(
        [r for r in eligible if r.get("avg_overall_score") is not None],
        key=lambda r: r["avg_overall_score"],
    )[:TOP_N]

    if needs_coaching:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🎯 Needs Coaching*\n" + "\n".join(
                    f"{i+1}. *{r['rep_name']}* — "
                    f"{_score_emoji(r['avg_overall_score'])} {_num(r['avg_overall_score'], 1)} avg "
                    f"({r['total_calls']} calls, {_pct(r.get('close_rate_pct'))} close)"
                    for i, r in enumerate(needs_coaching)
                ),
            },
        })

    # ── Top objections ───────────────────────────────────────────────────
    if top_objections:
        obj_lines = []
        for o in top_objections[:TOP_N]:
            src = o.get("lead_source") or "—"
            obj_lines.append(
                f"• *{o['objection_type']}* — {o['frequency']} times "
                f"({_pct(o.get('pct_of_total'))}) on _{src}_ leads"
            )
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🚧 Top Objections*\n" + "\n".join(obj_lines),
            },
        })

    return blocks


def build_weekly_fallback_text(week_start: str, total_calls: int, close_rate: float | None) -> str:
    if total_calls == 0:
        return f"Weekly report ({week_start}): no calls"
    return f"Weekly report ({week_start}): {total_calls} calls, {_pct(close_rate)} close rate"
