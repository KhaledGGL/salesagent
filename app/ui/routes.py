"""Server-rendered management UI for the Sales Coach.

Audience: 3 leadership users per client (CEO, Sales Manager, Client Manager)
sitting behind a Caddy basicauth gate. We deliberately avoid a JS build
step — Tailwind / HTMX / Chart.js are loaded via CDN in templates/base.html
so the UI ships in the same Docker image as the API and has zero frontend
toolchain to maintain.

Phase 1 status: route stubs only. Each page renders its template with the
shared base layout; data wiring lands in Phase 2.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# templates/ lives at app/templates/, this file at app/ui/routes.py
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

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
async def calls_list(request: Request) -> HTMLResponse:
    return _render(request, "calls.html", active="calls")


@router.get("/calls/{call_id}", response_class=HTMLResponse)
async def call_detail(request: Request, call_id: str) -> HTMLResponse:
    return _render(request, "call_detail.html", active="calls", call_id=call_id)


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
