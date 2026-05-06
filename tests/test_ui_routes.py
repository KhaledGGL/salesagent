"""Cross-cutting smoke tests for the UI routes.

Each page renders with the shared base layout, the nav links are present,
the active-tab highlight is correct, and dark mode classes ship. Data
correctness for individual pages lives in their dedicated test files
(test_ui_calls_list.py, test_ui_call_detail.py, etc.).

Uses an autouse fixture that mocks Supabase across every UI route call
with empty/permissive responses — enough for templates to render but
not asserting any specific data.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _self_chaining(execute_data, count=None):
    """Build a chain mock where every method returns self and only
    .execute() returns a response object with .data and .count."""
    from unittest.mock import MagicMock
    chain = MagicMock()
    for method in ("select", "gte", "lte", "eq", "neq", "order", "range",
                   "limit", "maybe_single", "single", "filter"):
        getattr(chain, method).return_value = chain
    resp = MagicMock()
    resp.data = execute_data
    resp.count = count
    chain.execute.return_value = resp
    return chain


@pytest.fixture(autouse=True)
def _stub_supabase(mocker):
    """Mock Supabase for every UI route in this file.

    The dashboard, reps list, sources, objections, therapist-mode, and
    reports pages all just render whatever data we feed them. Empty data
    keeps the templates rendering cleanly without 500s.

    For /ui/reps/:id we plant a fake rep row so the route doesn't 404;
    the rep_detail page's deeper data assertions live in its own file.
    """
    from unittest.mock import MagicMock

    def _table(name):
        # Most reads → empty. Single-row endpoints → small fake data.
        if name == "reps":
            # rep_detail uses .maybe_single() which we can't easily branch
            # on here — give it a fallback fake rep so the page renders.
            # We MUST give the maybe_single path its own MagicMock chain so
            # the override doesn't overwrite chain.execute() and break the
            # list-shaped queries the dashboard does (`.select().execute()`).
            chain = _self_chaining([], count=0)
            single_chain = MagicMock()
            fake_rep_resp = MagicMock()
            fake_rep_resp.data = {"id": "any", "name": "Fake Rep",
                                  "email": None, "is_active": True,
                                  "created_at": "2026-04-01T00:00:00Z"}
            single_chain.execute.return_value = fake_rep_resp
            chain.select.return_value.eq.return_value.maybe_single.return_value = single_chain
            return chain
        return _self_chaining([])

    fake_db = MagicMock()
    fake_db.table.side_effect = _table
    mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)


# ── Smoke: every page returns 200 + HTML + the shared shell ─────────────────

@pytest.mark.parametrize(
    "path",
    [
        "/ui/",
        "/ui/reps",
        "/ui/reps/some-rep-id",
        "/ui/sources",
        "/ui/objections",
        "/ui/therapist-mode",
        "/ui/reports",
        "/ui/reports?type=coaching",
        "/ui/reports?type=marketing",
    ],
)
def test_route_returns_200_html(client, path):
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}: {r.text[:200]}"
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert "<!doctype html>" in body
    assert "Sales Coach" in body
    # Nav must link to every other top-level page
    for link in ("/ui/calls", "/ui/reps", "/ui/sources",
                 "/ui/objections", "/ui/therapist-mode", "/ui/reports"):
        assert link in body, f"nav missing {link} on {path}"


# ── Active nav highlight ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path,expected_active",
    [
        ("/ui/", "Overview"),
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
    needle = f'font-medium">{expected_active}'
    assert needle in body, f"{path} should highlight {expected_active!r}"


# ── Layout / theme smoke checks ─────────────────────────────────────────────

def test_base_layout_loads_required_cdn_scripts(client):
    body = client.get("/ui/").text
    assert "cdn.tailwindcss.com" in body
    assert "htmx.org" in body
    assert "chart.js" in body.lower()


def test_base_layout_uses_dark_zinc_palette(client):
    body = client.get("/ui/").text
    assert "bg-zinc-950" in body
    assert 'class="dark"' in body


# ── URL_PREFIX wiring (path-stripping reverse proxy support) ────────────────

def test_url_prefix_applied_to_nav_links(client):
    from app.ui.routes import templates
    original = templates.env.globals.get("URL_PREFIX", "")
    templates.env.globals["URL_PREFIX"] = "/salesgrader"
    try:
        body = client.get("/ui/").text
        assert 'href="/salesgrader/ui/"' in body
        assert 'href="/salesgrader/ui/calls"' in body
        assert 'href="/salesgrader/ui/reps"' in body
        assert 'href="/salesgrader/ui/sources"' in body
        assert 'href="/salesgrader/ui/reports"' in body
    finally:
        templates.env.globals["URL_PREFIX"] = original


def test_url_prefix_empty_renders_clean_paths(client):
    body = client.get("/ui/").text
    assert 'href="/ui/calls"' in body
    assert 'href="/ui/reps"' in body


# ── Detail-page path argument smoke (rep is shown via the autouse stub) ─────

def test_rep_detail_renders_rep_data(client):
    body = client.get("/ui/reps/rep-9").text
    # The autouse stub returns a "Fake Rep" — confirms the join + render path
    assert "Fake Rep" in body
