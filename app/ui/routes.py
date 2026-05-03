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

from fastapi import APIRouter, HTTPException, Request
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
    return _render(request, "dashboard.html", active="dashboard")


@router.get("/calls", response_class=HTMLResponse)
async def calls_list(
    request: Request,
    rep_id: str | None = None,
    outcome: str | None = None,
    source: str | None = None,
    days: int = 30,
    page: int = 1,
) -> HTMLResponse:
    """Filterable, paginated list of recent calls.

    Filters are passed as query params so each combination is a
    bookmarkable URL — no HTMX needed for v1, plain GET form submit.
    """
    db = get_supabase()

    # Reps for the filter dropdown — small table, one round-trip.
    reps = db.table("reps").select("id, name").order("name").execute().data or []

    # Time window — default 30 days mirrors v_rep_performance_30d.
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=max(days, 1))).isoformat()

    # Base query. We embed the rep name + just the score fields the table
    # row needs (avoid pulling the full scorecard into a list view).
    q = (
        db.table("calls")
        .select(
            "id, lead_name, lead_source, outcome, called_at, status, rep_id, "
            "reps(name), call_scores(overall_score, therapist_mode_flag)",
            count="exact",
        )
        .gte("called_at", cutoff_iso)
        .order("called_at", desc=True)
    )
    if rep_id:
        q = q.eq("rep_id", rep_id)
    if outcome:
        q = q.eq("outcome", outcome)
    if source:
        q = q.eq("lead_source", source)

    # Pagination via .range — Supabase translates this to LIMIT/OFFSET.
    page = max(page, 1)
    start = (page - 1) * CALLS_PER_PAGE
    q = q.range(start, start + CALLS_PER_PAGE - 1)

    resp = q.execute()
    calls = resp.data or []
    total = getattr(resp, "count", None) or 0
    total_pages = max((total + CALLS_PER_PAGE - 1) // CALLS_PER_PAGE, 1)

    return _render(
        request,
        "calls.html",
        active="calls",
        calls=calls,
        reps=reps,
        filters={
            "rep_id": rep_id or "",
            "outcome": outcome or "",
            "source": source or "",
            "days": days,
        },
        page=page,
        total=total,
        total_pages=total_pages,
        per_page=CALLS_PER_PAGE,
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
    score_rows = call.get("call_scores") or []
    # Supabase returns the embedded join as a list; pick the first row if any.
    score = score_rows[0] if score_rows else None

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
    return _render(request, "reps.html", active="reps")


@router.get("/reps/{rep_id}", response_class=HTMLResponse)
async def rep_detail(request: Request, rep_id: str) -> HTMLResponse:
    return _render(request, "rep_detail.html", active="reps", rep_id=rep_id)


@router.get("/sources", response_class=HTMLResponse)
async def sources(request: Request) -> HTMLResponse:
    return _render(request, "sources.html", active="sources")


@router.get("/objections", response_class=HTMLResponse)
async def objections(request: Request) -> HTMLResponse:
    return _render(request, "objections.html", active="objections")


@router.get("/therapist-mode", response_class=HTMLResponse)
async def therapist_mode(request: Request) -> HTMLResponse:
    return _render(request, "therapist_mode.html", active="therapist")


@router.get("/reports", response_class=HTMLResponse)
async def reports(request: Request) -> HTMLResponse:
    return _render(request, "reports.html", active="reports")
