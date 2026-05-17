"""Shared formatting / styling helpers for the management UI templates.

Kept as pure functions so they're trivial to unit-test and don't need
template-engine context. Each helper returns a Tailwind class string or
a formatted display value — never HTML, so templates stay in charge of
markup.

Color palette is the dark-mode professional palette (zinc-base body
with translucent accent fills using color-500/10 + color-500/20 rings).
"""

from __future__ import annotations


# ── Score → color class (matches the Slack scorecard emoji thresholds) ──────
#
# 8-10 = emerald (good), 5-7 = amber (mediocre), 1-4 = rose (bad).
# Same bands the scorecard message uses so reps see consistent signaling
# whether they're reading Slack or the dashboard.

def score_color_class(score: int | None) -> str:
    if score is None:
        return "text-zinc-400 bg-zinc-800/60 ring-zinc-700/60"
    if score >= 8:
        return "text-emerald-400 bg-emerald-500/10 ring-emerald-500/20"
    if score >= 5:
        return "text-amber-400 bg-amber-500/10 ring-amber-500/20"
    return "text-rose-400 bg-rose-500/10 ring-rose-500/20"


def score_dot_class(score: int | None) -> str:
    """Just the dot color for tight score badges."""
    if score is None:
        return "bg-zinc-500"
    if score >= 8:
        return "bg-emerald-500"
    if score >= 5:
        return "bg-amber-500"
    return "bg-rose-500"


# ── Outcome → badge class (sold / not_sold / follow_up are AI-derived) ──────

def outcome_badge_class(outcome: str | None) -> str:
    return {
        "sold":         "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20",
        "not_sold":     "bg-rose-500/10 text-rose-400 ring-rose-500/20",
        "follow_up":    "bg-amber-500/10 text-amber-400 ring-amber-500/20",
        "no_show":      "bg-zinc-800/60 text-zinc-400 ring-zinc-700/60",
        "rescheduled":  "bg-sky-500/10 text-sky-400 ring-sky-500/20",
    }.get(outcome or "", "bg-zinc-800/60 text-zinc-400 ring-zinc-700/60")


def outcome_label(outcome: str | None) -> str:
    return {
        "sold":         "Sold",
        "not_sold":     "Not sold",
        "follow_up":    "Follow-up",
        "no_show":      "No show",
        "rescheduled":  "Rescheduled",
    }.get(outcome or "", "—")


# ── Severity / category styling for coaching moments ────────────────────────

def severity_class(severity: str | None) -> str:
    return {
        "high":   "bg-rose-500/10 text-rose-400 ring-rose-500/20",
        "medium": "bg-amber-500/10 text-amber-400 ring-amber-500/20",
        "low":    "bg-zinc-800/60 text-zinc-400 ring-zinc-700/60",
    }.get(severity or "", "bg-zinc-800/60 text-zinc-400 ring-zinc-700/60")


def category_label(category: str | None) -> str:
    """Render snake_case categories for human eyes."""
    if not category:
        return "—"
    return category.replace("_", " ").title()


def handling_quality_class(quality: str | None) -> str:
    return {
        "excellent": "bg-emerald-500/10 text-emerald-400 ring-emerald-500/20",
        "good":      "bg-sky-500/10 text-sky-400 ring-sky-500/20",
        "fair":      "bg-amber-500/10 text-amber-400 ring-amber-500/20",
        "poor":      "bg-rose-500/10 text-rose-400 ring-rose-500/20",
    }.get(quality or "", "bg-zinc-800/60 text-zinc-400 ring-zinc-700/60")


# ── Misc formatters ─────────────────────────────────────────────────────────

def format_seconds_to_mmss(seconds: int | float | None) -> str:
    """125 → '2:05'. None or negative → '—'."""
    if seconds is None or seconds < 0:
        return "—"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def format_confidence_pct(confidence: float | None) -> str | None:
    """0.92 → '92%'. None → None (template can decide whether to render)."""
    if confidence is None:
        return None
    return f"{int(round(float(confidence) * 100))}%"


def format_duration_minutes(seconds: int | float | None) -> str:
    """Display call duration as compact minutes — '7m 12s'."""
    if seconds is None or seconds < 0:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    return f"{s // 60}m {s % 60:02d}s"


# ── Supabase embed-shape normalizer ─────────────────────────────────────────

def first_or_dict(value):
    """Normalize a Supabase embedded resource to a single row or None.

    PostgREST / supabase-py returns embeds as either a list (one-to-many)
    or a single dict (one-to-one when the foreign key has a UNIQUE
    constraint, e.g. call_scores.call_id). Templates and routes need to
    handle both shapes — this helper does that uniformly.
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value[0] if value else None
    return value


# ── Live aggregation for the dashboard ──────────────────────────────────────
#
# These replace the old v_weekly_overview / v_rep_performance_weekly views
# for the dashboard, which were hardcoded to "previous completed week".
# Doing it in Python lets the dashboard pick any window (this week, last
# month, rolling 30d, …) without piling more parameterised SQL views in.
# Volume is small (single client per VPS, hundreds of calls/week max), so
# pulling rows + folding in Python is fine — and trivially unit-testable.

def compute_overview_from_rows(rows: list[dict]) -> dict:
    """Roll a list of `calls` rows (with embedded `call_scores`) into the
    KPI shape the dashboard cards expect.

    Only `status='scored'` rows count toward totals — same semantics as
    the old SQL view, so an in-flight call doesn't deflate close rate.
    """
    total = sold = tm = 0
    scores: list[float] = []
    for c in rows:
        if c.get("status") != "scored":
            continue
        total += 1
        if c.get("outcome") == "sold":
            sold += 1
        sc = first_or_dict(c.get("call_scores")) or {}
        if sc.get("overall_score") is not None:
            scores.append(sc["overall_score"])
        if sc.get("therapist_mode_flag"):
            tm += 1
    return {
        "total_calls":          total,
        "sold_calls":           sold,
        "close_rate_pct":       round(sold * 100.0 / total, 1) if total else None,
        "avg_overall_score":    round(sum(scores) / len(scores), 2) if scores else None,
        "therapist_mode_count": tm,
    }


def compute_rep_perf_from_rows(rows: list[dict], reps_by_id: dict[str, str]) -> list[dict]:
    """Group scored calls by rep and produce the per-rep performance shape
    the leaderboards expect (matches the columns the v_rep_performance_*
    views used to return: rep_id, rep_name, total_calls, sold_calls,
    close_rate_pct, avg_overall_score, therapist_mode_count).

    Reps with zero in-window calls are omitted — the dashboard only ranks
    reps who actually showed up in the window. The 3-call qualification
    threshold is applied at the route layer, not here.
    """
    per_rep: dict[str, dict] = {}
    for c in rows:
        if c.get("status") != "scored":
            continue
        rid = c.get("rep_id")
        if not rid:
            continue
        bucket = per_rep.setdefault(rid, {
            "rep_id":               rid,
            "rep_name":             reps_by_id.get(rid, "Unknown"),
            "total_calls":          0,
            "sold_calls":           0,
            "therapist_mode_count": 0,
            "_scores":              [],
        })
        bucket["total_calls"] += 1
        if c.get("outcome") == "sold":
            bucket["sold_calls"] += 1
        sc = first_or_dict(c.get("call_scores")) or {}
        if sc.get("overall_score") is not None:
            bucket["_scores"].append(sc["overall_score"])
        if sc.get("therapist_mode_flag"):
            bucket["therapist_mode_count"] += 1

    out = []
    for r in per_rep.values():
        scs = r.pop("_scores")
        r["close_rate_pct"]    = round(r["sold_calls"] * 100.0 / r["total_calls"], 1) if r["total_calls"] else None
        r["avg_overall_score"] = round(sum(scs) / len(scs), 2) if scs else None
        out.append(r)
    return out
