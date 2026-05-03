"""Shared formatting / styling helpers for the management UI templates.

Kept as pure functions so they're trivial to unit-test and don't need
template-engine context. Each helper returns a Tailwind class string or
a formatted display value — never HTML, so templates stay in charge of
markup.
"""

from __future__ import annotations


# ── Score → color class (matches the Slack scorecard emoji thresholds) ──────
#
# 8-10 = green (good), 5-7 = yellow (mediocre), 1-4 = red (bad). Same
# bands the scorecard message uses so reps see consistent signaling
# whether they're reading Slack or the dashboard.

def score_color_class(score: int | None) -> str:
    if score is None:
        return "text-slate-400 bg-slate-100"
    if score >= 8:
        return "text-emerald-700 bg-emerald-50"
    if score >= 5:
        return "text-amber-700 bg-amber-50"
    return "text-rose-700 bg-rose-50"


def score_dot_class(score: int | None) -> str:
    """Just the dot color for tight score badges."""
    if score is None:
        return "bg-slate-300"
    if score >= 8:
        return "bg-emerald-500"
    if score >= 5:
        return "bg-amber-500"
    return "bg-rose-500"


# ── Outcome → badge class (sold / not_sold / follow_up are the AI-derived ones) ─

def outcome_badge_class(outcome: str | None) -> str:
    return {
        "sold":         "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
        "not_sold":     "bg-rose-50 text-rose-700 ring-rose-600/20",
        "follow_up":    "bg-amber-50 text-amber-700 ring-amber-600/20",
        "no_show":      "bg-slate-100 text-slate-600 ring-slate-500/20",
        "rescheduled": "bg-sky-50 text-sky-700 ring-sky-600/20",
    }.get(outcome or "", "bg-slate-50 text-slate-500 ring-slate-400/20")


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
        "high":   "bg-rose-50 text-rose-700 ring-rose-600/20",
        "medium": "bg-amber-50 text-amber-700 ring-amber-600/20",
        "low":    "bg-slate-100 text-slate-600 ring-slate-500/20",
    }.get(severity or "", "bg-slate-100 text-slate-600 ring-slate-500/20")


def category_label(category: str | None) -> str:
    """Render snake_case categories for human eyes."""
    if not category:
        return "—"
    return category.replace("_", " ").title()


def handling_quality_class(quality: str | None) -> str:
    return {
        "excellent": "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
        "good":      "bg-sky-50 text-sky-700 ring-sky-600/20",
        "fair":      "bg-amber-50 text-amber-700 ring-amber-600/20",
        "poor":      "bg-rose-50 text-rose-700 ring-rose-600/20",
    }.get(quality or "", "bg-slate-100 text-slate-600 ring-slate-500/20")


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
