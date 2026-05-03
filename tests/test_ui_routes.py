"""Smoke tests for the UI route stubs.

Phase 1 scope: every page renders with the shared base layout, the nav
links to all the right places, and the active-tab highlight is correct.
Data wiring is Phase 2 — these tests are deliberately structural, not
about the data each page will eventually display.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


# ── Each route returns 200 with HTML and the shared shell ───────────────────

# Routes that don't need a DB — pure stub or path-arg-only.
# /ui/calls/:id has its own dedicated test file (test_ui_call_detail.py)
# because it queries Supabase and needs full mocking.
@pytest.mark.parametrize(
    "path",
    [
        "/ui/",
        "/ui/calls",
        "/ui/reps",
        "/ui/reps/rep-uuid",
        "/ui/sources",
        "/ui/objections",
        "/ui/therapist-mode",
        "/ui/reports",
    ],
)
def test_route_returns_200_html(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # Base shell markers
    assert "<!doctype html>" in body
    assert "Sales Coach" in body
    # Nav must link to every other top-level page so users can navigate
    # between sections without back-button gymnastics.
    for link in (
        '/ui/"',
        "/ui/calls",
        "/ui/reps",
        "/ui/sources",
        "/ui/objections",
        "/ui/therapist-mode",
        "/ui/reports",
    ):
        assert link in body, f"nav missing {link} on {path}"


# ── Active-tab highlighting (the small but important detail) ────────────────

# /ui/calls/:id active-tab check lives in test_ui_call_detail.py
# since that page needs DB mocks.
@pytest.mark.parametrize(
    "path,expected_active",
    [
        ("/ui/", "Overview"),
        ("/ui/calls", "Calls"),
        ("/ui/reps", "Reps"),
        ("/ui/reps/abc", "Reps"),
        ("/ui/sources", "Sources"),
        ("/ui/objections", "Objections"),
        ("/ui/therapist-mode", "Therapist Mode"),
        ("/ui/reports", "Reports"),
    ],
)
def test_active_nav_highlight(client, path, expected_active):
    body = client.get(path).text
    # font-medium is the tailwind class our template applies to the active link
    # — find it adjacent to the expected nav label.
    assert f"font-medium" in body
    # Crude but effective: the active label should appear near the
    # font-medium class in the nav block. Search for the label inside an
    # anchor tagged with font-medium.
    needle = f'font-medium">{expected_active}'
    assert needle in body, f"{path} should highlight {expected_active!r}"


# ── Detail pages surface their ID parameter (proof the path arg is wired) ───
# /ui/calls/:id is covered in test_ui_call_detail.py with proper DB mocks.

def test_rep_detail_renders_rep_id(client):
    body = client.get("/ui/reps/rep-9").text
    assert "rep-9" in body


# ── External assets are loaded via CDN (no JS toolchain in this project) ────

def test_base_layout_loads_required_cdn_scripts(client):
    body = client.get("/ui/").text
    # Tailwind utility classes only work if the CDN script tag is present
    assert "cdn.tailwindcss.com" in body
    # HTMX powers the interactive bits we'll add in Phase 2
    assert "htmx.org" in body
    # Chart.js is there for the trend graphs the dashboard will render
    assert "chart.js" in body.lower()
