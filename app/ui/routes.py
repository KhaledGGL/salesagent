"""Server-rendered management UI for the Sales Coach.

Audience: 3 leadership users per client (CEO, Sales Manager, Client Manager)
sitting behind a Caddy basicauth gate. We deliberately avoid a JS build
step — Tailwind / HTMX / Chart.js are loaded via CDN in templates/base.html
so the UI ships in the same Docker image as the API and has zero frontend
toolchain to maintain.

Phase 1 status: route stubs only. Each page renders its template with the
shared base layout; data wiring lands in Phase 2.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_supabase
from app.ui import helpers
from config import settings

# Page size for the calls list. Big enough that most weeks fit on one page,
# small enough that the page renders fast even on a fresh DB.
CALLS_PER_PAGE = 25

# templates/ lives at app/templates/, this file at app/ui/routes.py
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Wire helpers + the URL prefix into the Jinja env so templates can call
# them directly without each route having to pass them as context kwargs.
# URL_PREFIX is the public-facing path (e.g. "/salesgrader") that Caddy
# strips before forwarding to us; templates prepend it to every link.
templates.env.globals["h"] = helpers
templates.env.globals["URL_PREFIX"] = settings.url_prefix

router = APIRouter(prefix="/ui", tags=["ui"])


def _render(request: Request, template: str, active: str, **ctx) -> HTMLResponse:
    """Thin wrapper so every route consistently passes `active` (for nav
    highlighting) and the request object that Jinja2Templates requires."""
    return templates.TemplateResponse(
        request,
        template,
        {"active": active, **ctx},
    )


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    """Landing page — KPI cards, leaderboard, alerts, latest insights, recent calls."""
    db = get_supabase()

    # Org-wide overview for the previous completed week
    overview_resp = db.table("v_weekly_overview").select("*").execute()
    overview_rows = overview_resp.data or []
    overview = overview_rows[0] if overview_rows else {}

    # Per-rep performance — same view the weekly Slack report uses.
    # Min 3 calls to qualify for leaderboards (avoids single-call outliers).
    rep_perf = (
        db.table("v_rep_performance_weekly").select("*").execute().data or []
    )
    qualified = [r for r in rep_perf if (r.get("total_calls") or 0) >= 3]
    top_performers = sorted(
        qualified,
        key=lambda r: (r.get("close_rate_pct") or 0, r.get("avg_overall_score") or 0),
        reverse=True,
    )[:3]
    needs_coaching = sorted(
        qualified,
        key=lambda r: (r.get("avg_overall_score") or 99),
    )[:3]

    # 30-day rolling rep table for the trend section
    rep_30d = (
        db.table("v_rep_performance_30d").select("*").execute().data or []
    )

    # Most-recent calls (last 8) for the activity feed
    recent_calls = (
        db.table("calls")
        .select("id, lead_name, lead_source, outcome, called_at, status, "
                "reps(name), call_scores(overall_score, therapist_mode_flag)")
        .order("called_at", desc=True)
        .limit(8)
        .execute()
        .data
        or []
    )

    # Latest of each weekly report type for the insights cards
    latest_insights: dict[str, dict] = {}
    for rtype in ("sales", "coaching", "marketing"):
        rows = (
            db.table("weekly_reports")
            .select("*")
            .eq("report_type", rtype)
            .order("week_start", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            latest_insights[rtype] = rows[0]

    return _render(
        request,
        "dashboard.html",
        active="dashboard",
        overview=overview,
        top_performers=top_performers,
        needs_coaching=needs_coaching,
        rep_30d=rep_30d,
        recent_calls=recent_calls,
        latest_insights=latest_insights,
    )


def _apply_in_filter(q, field: str, values: list[str], op: str):
    """Apply IN / NOT IN filter to a Supabase query builder.

    Empty values list = no-op (no filter applied → all values pass).
    op='not_in' uses .filter() with PostgREST's not.in(...) operator
    since supabase-py 2.28's higher-level NOT chain isn't reliable.
    """
    if not values:
        return q
    if op == "not_in":
        # PostgREST list values must be parenthesised
        return q.filter(field, "not.in", "(" + ",".join(values) + ")")
    return q.in_(field, values)


def _distinct_text_values(db, column: str, limit: int = 500) -> list[str]:
    """Pull distinct non-null values from a calls column for a dropdown.

    Done in Python because supabase-py doesn't expose DISTINCT directly.
    Cheap on small tables (one round-trip, capped fetch). For a multi-
    tenant single-VPS-per-client deployment this stays well under any
    relevant ceiling.
    """
    rows = (
        db.table("calls")
        .select(column)
        .not_.is_(column, "null")
        .limit(limit)
        .execute()
        .data
        or []
    )
    return sorted({r[column] for r in rows if r.get(column)})


@router.get("/calls", response_class=HTMLResponse)
async def calls_list(
    request: Request,
    # Multi-value filters: each can be passed multiple times in the query
    # string (?rep_id=r1&rep_id=r2). Each has a paired _op selecting
    # include vs. exclude semantics.
    rep_id:        list[str] = Query(default=[]),
    rep_op:        str       = "in",
    outcome:       list[str] = Query(default=[]),
    outcome_op:    str       = "in",
    source:        list[str] = Query(default=[]),
    source_op:     str       = "in",
    utm_source:    list[str] = Query(default=[]),
    utm_source_op: str       = "in",
    utm_medium:    list[str] = Query(default=[]),
    utm_medium_op: str       = "in",
    # Free-text contains filters for unbounded UTM fields
    utm_campaign:  str       = "",
    utm_content:   str       = "",
    utm_term:      str       = "",
    # Date range — overrides `days` if either bound is set
    start_date:    str       = "",
    end_date:      str       = "",
    days:          int       = 30,
    page:          int       = 1,
) -> HTMLResponse:
    """Filterable, paginated list of recent calls.

    Filter semantics:
      - Within a single field: OR (e.g. outcome IN sold, follow_up)
      - Across fields:         AND (e.g. (rep IN [Sarah, Mike]) AND (source = meta))
      - Per-field include/exclude via the matching _op param
      - Free-text fields use case-insensitive 'contains'

    Every combination is a bookmarkable URL (plain GET form submit, no JS).
    """
    db = get_supabase()

    # ── Dropdown options ──────────────────────────────────────────────
    reps = db.table("reps").select("id, name").order("name").execute().data or []
    utm_source_options = _distinct_text_values(db, "utm_source")
    utm_medium_options = _distinct_text_values(db, "utm_medium")

    # ── Build the calls query ─────────────────────────────────────────
    q = (
        db.table("calls")
        .select(
            "id, lead_name, lead_source, outcome, called_at, status, rep_id, "
            "utm_source, utm_campaign, "
            "reps(name), call_scores(overall_score, therapist_mode_flag)",
            count="exact",
        )
        .order("called_at", desc=True)
    )

    # Date bounds — explicit dates win over the preset window
    if start_date or end_date:
        if start_date:
            q = q.gte("called_at", start_date)
        if end_date:
            # Make end_date inclusive — bump to end-of-day if user passed YYYY-MM-DD
            end_iso = end_date if "T" in end_date else f"{end_date}T23:59:59+00:00"
            q = q.lte("called_at", end_iso)
    elif days:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).isoformat()
        q = q.gte("called_at", cutoff_iso)

    # Multi-value filters with include/exclude
    q = _apply_in_filter(q, "rep_id",      rep_id,      rep_op)
    q = _apply_in_filter(q, "outcome",     outcome,     outcome_op)
    q = _apply_in_filter(q, "lead_source", source,      source_op)
    q = _apply_in_filter(q, "utm_source",  utm_source,  utm_source_op)
    q = _apply_in_filter(q, "utm_medium",  utm_medium,  utm_medium_op)

    # Free-text 'contains' for unbounded UTM fields
    if utm_campaign:
        q = q.ilike("utm_campaign", f"%{utm_campaign}%")
    if utm_content:
        q = q.ilike("utm_content", f"%{utm_content}%")
    if utm_term:
        q = q.ilike("utm_term", f"%{utm_term}%")

    # Pagination
    page = max(page, 1)
    start = (page - 1) * CALLS_PER_PAGE
    q = q.range(start, start + CALLS_PER_PAGE - 1)

    resp = q.execute()
    calls = resp.data or []
    total = getattr(resp, "count", None) or 0
    total_pages = max((total + CALLS_PER_PAGE - 1) // CALLS_PER_PAGE, 1)

    # ── Build a stable query-string for pagination links that preserves
    # every active filter (so 'Next →' on a filtered view stays filtered).
    qs_params: list[tuple[str, str]] = []
    for v in rep_id:     qs_params.append(("rep_id", v))
    if rep_op != "in":   qs_params.append(("rep_op", rep_op))
    for v in outcome:    qs_params.append(("outcome", v))
    if outcome_op != "in": qs_params.append(("outcome_op", outcome_op))
    for v in source:     qs_params.append(("source", v))
    if source_op != "in": qs_params.append(("source_op", source_op))
    for v in utm_source: qs_params.append(("utm_source", v))
    if utm_source_op != "in": qs_params.append(("utm_source_op", utm_source_op))
    for v in utm_medium: qs_params.append(("utm_medium", v))
    if utm_medium_op != "in": qs_params.append(("utm_medium_op", utm_medium_op))
    if utm_campaign:     qs_params.append(("utm_campaign", utm_campaign))
    if utm_content:      qs_params.append(("utm_content", utm_content))
    if utm_term:         qs_params.append(("utm_term", utm_term))
    if start_date:       qs_params.append(("start_date", start_date))
    if end_date:         qs_params.append(("end_date", end_date))
    if not (start_date or end_date) and days != 30:
        qs_params.append(("days", str(days)))
    page_qs = urlencode(qs_params)

    return _render(
        request,
        "calls.html",
        active="calls",
        calls=calls,
        reps=reps,
        utm_source_options=utm_source_options,
        utm_medium_options=utm_medium_options,
        filters={
            "rep_id":          rep_id,
            "rep_op":          rep_op,
            "outcome":         outcome,
            "outcome_op":      outcome_op,
            "source":          source,
            "source_op":       source_op,
            "utm_source":      utm_source,
            "utm_source_op":   utm_source_op,
            "utm_medium":      utm_medium,
            "utm_medium_op":   utm_medium_op,
            "utm_campaign":    utm_campaign,
            "utm_content":     utm_content,
            "utm_term":        utm_term,
            "start_date":      start_date,
            "end_date":        end_date,
            "days":            days,
        },
        any_filter_active=bool(
            rep_id or outcome or source or utm_source or utm_medium
            or utm_campaign or utm_content or utm_term
            or start_date or end_date
        ),
        page=page,
        total=total,
        total_pages=total_pages,
        per_page=CALLS_PER_PAGE,
        page_qs=page_qs,
    )


@router.get("/calls/{call_id}", response_class=HTMLResponse)
async def call_detail(request: Request, call_id: str) -> HTMLResponse:
    """Full picture of a single scored call: scorecard + AI summary +
    coaching moments + objections + transcript. The page Sales Manager
    actually does coaching from."""
    db = get_supabase()

    # Match the join pattern used by notify_scorecard so we hit a single
    # round-trip for the parent + scorecard + rep, then a couple more
    # for the child collections (which have their own ordering).
    call_resp = (
        db.table("calls")
        .select("*, reps(name), call_scores(*)")
        .eq("id", call_id)
        .maybe_single()
        .execute()
    )

    # supabase-py 2.28+ returns None directly when no row matches.
    if call_resp is None or not call_resp.data:
        raise HTTPException(status_code=404, detail="Call not found")

    call = call_resp.data
    # Supabase embeds call_scores as a single dict (UNIQUE FK) — but it can
    # also come back as a list depending on supabase-py version / query.
    # The helper normalizes both shapes.
    score = helpers.first_or_dict(call.get("call_scores"))

    coaching = (
        db.table("coaching_moments")
        .select("*")
        .eq("call_id", call_id)
        .order("timestamp_seconds")
        .execute()
        .data
        or []
    )
    objections = (
        db.table("call_objections")
        .select("*")
        .eq("call_id", call_id)
        .order("timestamp_seconds")
        .execute()
        .data
        or []
    )

    return _render(
        request,
        "call_detail.html",
        active="calls",
        call_id=call_id,
        call=call,
        rep_name=(call.get("reps") or {}).get("name") or "Unknown rep",
        score=score,
        coaching=coaching,
        objections=objections,
    )


@router.get("/reps", response_class=HTMLResponse)
async def reps_list(request: Request) -> HTMLResponse:
    """Roster + 30-day performance per rep, ranked by overall score."""
    db = get_supabase()
    rows = (
        db.table("v_rep_performance_30d")
        .select("*")
        .order("avg_overall_score", desc=True, nullsfirst=False)
        .execute()
        .data
        or []
    )
    return _render(request, "reps.html", active="reps", reps=rows)


@router.get("/reps/{rep_id}", response_class=HTMLResponse)
async def rep_detail(request: Request, rep_id: str) -> HTMLResponse:
    """Per-rep deep-dive: stats, score trends, coaching effectiveness check,
    coaching moments grouped by category, recent calls.

    The coaching effectiveness check is the central insight on this page —
    for each category the rep was ever coached on, we compute the avg score
    in that category before vs after the most recent coaching moment so the
    Sales Manager can see whether intervention actually moved the needle.
    """
    db = get_supabase()

    # Rep row
    rep_row = (
        db.table("reps")
        .select("id, name, email, is_active, created_at")
        .eq("id", rep_id)
        .maybe_single()
        .execute()
    )
    if rep_row is None or not rep_row.data:
        raise HTTPException(status_code=404, detail="Rep not found")
    rep = rep_row.data

    # 30-day stats row from the existing view (matches the leaderboard)
    perf_rows = (
        db.table("v_rep_performance_30d").select("*").eq("rep_id", rep_id).execute().data or []
    )
    perf = perf_rows[0] if perf_rows else {}

    # All scored calls for this rep in the last 90 days (chart + effectiveness)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    scored_calls = (
        db.table("calls")
        .select(
            "id, lead_name, lead_source, outcome, called_at, status, "
            "call_scores(overall_score, rapport_score, diagnosis_score, "
            "objection_score, close_score, compliance_score, therapist_mode_flag)"
        )
        .eq("rep_id", rep_id)
        .eq("status", "scored")
        .gte("called_at", cutoff)
        .order("called_at")
        .execute()
        .data
        or []
    )

    # Flatten the score join so the template can iterate cleanly
    timeline = []
    for c in scored_calls:
        sc = helpers.first_or_dict(c.get("call_scores")) or {}
        if not sc:
            continue
        timeline.append({
            "call_id": c["id"],
            "called_at": c.get("called_at"),
            "overall": sc.get("overall_score"),
            "rapport": sc.get("rapport_score"),
            "diagnosis": sc.get("diagnosis_score"),
            "objection": sc.get("objection_score"),
            "close": sc.get("close_score"),
            "compliance": sc.get("compliance_score"),
            "outcome": c.get("outcome"),
            "lead_name": c.get("lead_name"),
        })

    # Coaching moments grouped by category
    coaching_rows = (
        db.table("coaching_moments")
        .select("id, category, severity, note, timestamp_seconds, created_at, "
                "calls!inner(rep_id, called_at)")
        .eq("calls.rep_id", rep_id)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

    # Map category → list[moments], preserving recency
    by_category: dict[str, list[dict]] = {}
    for m in coaching_rows:
        cat = m.get("category") or "other"
        by_category.setdefault(cat, []).append(m)

    # Coaching effectiveness check — for each category the rep was coached on,
    # split timeline at the most recent coaching date and compare averages.
    effectiveness = []
    cat_to_score_field = {
        "rapport": "rapport",
        "diagnosis": "diagnosis",
        "objection_handling": "objection",
        "close": "close",
        "compliance": "compliance",
    }
    for cat, score_field in cat_to_score_field.items():
        moments = by_category.get(cat) or []
        if not moments:
            continue
        # Most recent coaching date for this category (created_at on the row)
        anchor = max((m.get("created_at") or "") for m in moments)
        if not anchor:
            continue
        before = [t[score_field] for t in timeline
                  if t.get("called_at") and t["called_at"] < anchor and t[score_field] is not None]
        after = [t[score_field] for t in timeline
                 if t.get("called_at") and t["called_at"] >= anchor and t[score_field] is not None]
        if not before and not after:
            continue
        avg_before = round(sum(before) / len(before), 2) if before else None
        avg_after = round(sum(after) / len(after), 2) if after else None
        delta = (round(avg_after - avg_before, 2)
                 if (avg_before is not None and avg_after is not None) else None)
        effectiveness.append({
            "category": cat,
            "anchor_date": anchor[:10],
            "before_avg": avg_before,
            "after_avg": avg_after,
            "delta": delta,
            "before_count": len(before),
            "after_count": len(after),
            "moments_count": len(moments),
        })

    return _render(
        request,
        "rep_detail.html",
        active="reps",
        rep_id=rep_id,
        rep=rep,
        perf=perf,
        timeline=timeline,
        coaching_by_category=by_category,
        effectiveness=effectiveness,
    )


@router.get("/sources", response_class=HTMLResponse)
async def sources(request: Request) -> HTMLResponse:
    """Lead-source comparison — the marketing-loop view."""
    db = get_supabase()
    source_perf = (
        db.table("v_weekly_source_performance").select("*").execute().data or []
    )
    cold_warm = (
        db.table("v_cold_warm_comparison").select("*").execute().data or []
    )
    # Top objections per source from this week
    src_objections = (
        db.table("v_top_objections_weekly").select("*").execute().data or []
    )
    # Group objections by source for the per-source breakdown
    obj_by_source: dict[str, list[dict]] = {}
    for o in src_objections:
        obj_by_source.setdefault(o.get("lead_source") or "unknown", []).append(o)

    return _render(
        request,
        "sources.html",
        active="sources",
        source_perf=source_perf,
        cold_warm=cold_warm,
        obj_by_source=obj_by_source,
    )


@router.get("/objections", response_class=HTMLResponse)
async def objections(request: Request) -> HTMLResponse:
    """Top objection types this week + handling-quality rollup."""
    db = get_supabase()
    top = (
        db.table("v_top_objections_weekly").select("*").execute().data or []
    )

    # Aggregate by type across sources for the headline table
    by_type: dict[str, dict] = {}
    for o in top:
        t = o.get("objection_type") or "other"
        bucket = by_type.setdefault(t, {"objection_type": t, "frequency": 0, "sources": {}})
        bucket["frequency"] += int(o.get("frequency") or 0)
        bucket["sources"][o.get("lead_source") or "unknown"] = o.get("frequency") or 0
    rolled = sorted(by_type.values(), key=lambda b: b["frequency"], reverse=True)
    total_freq = sum(b["frequency"] for b in rolled) or 1
    for b in rolled:
        b["pct"] = round(b["frequency"] * 100.0 / total_freq, 1)

    # Handling quality rollup over the last 30 days for sentiment context
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    qual_rows = (
        db.table("call_objections")
        .select("handling_quality, calls!inner(called_at, status)")
        .eq("calls.status", "scored")
        .gte("calls.called_at", cutoff)
        .execute()
        .data
        or []
    )
    quality_counts: dict[str, int] = {}
    for r in qual_rows:
        q = r.get("handling_quality") or "unknown"
        quality_counts[q] = quality_counts.get(q, 0) + 1

    return _render(
        request,
        "objections.html",
        active="objections",
        rolled=rolled,
        quality_counts=quality_counts,
        total_freq=total_freq,
    )


@router.get("/therapist-mode", response_class=HTMLResponse)
async def therapist_mode(request: Request) -> HTMLResponse:
    """Therapist-mode trend by week + recent flagged calls with reasons."""
    db = get_supabase()
    trend = (
        db.table("v_therapist_mode_trend").select("*").execute().data or []
    )

    # Recent flagged calls (last 30 days) with the AI's reason text
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    flagged = (
        db.table("calls")
        .select("id, lead_name, called_at, reps(name), "
                "call_scores!inner(therapist_mode_flag, therapist_mode_reason, overall_score)")
        .eq("status", "scored")
        .eq("call_scores.therapist_mode_flag", True)
        .gte("called_at", cutoff)
        .order("called_at", desc=True)
        .limit(50)
        .execute()
        .data
        or []
    )

    return _render(
        request,
        "therapist_mode.html",
        active="therapist",
        trend=trend,
        flagged=flagged,
    )


@router.get("/reports", response_class=HTMLResponse)
async def reports(request: Request, type: str = "sales") -> HTMLResponse:
    """Archive of all generated weekly reports — sales / coaching / marketing.
    Reads from the weekly_reports table populated by the Monday Celery tasks."""
    db = get_supabase()
    rtype = type if type in ("sales", "coaching", "marketing") else "sales"

    rows = (
        db.table("weekly_reports")
        .select("*")
        .eq("report_type", rtype)
        .order("week_start", desc=True)
        .execute()
        .data
        or []
    )

    return _render(
        request,
        "reports.html",
        active="reports",
        rtype=rtype,
        reports=rows,
    )
