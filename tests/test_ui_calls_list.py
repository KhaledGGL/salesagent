"""Tests for the /ui/calls listing route.

Mocks Supabase to cover:
- Empty state when no calls match
- Filter wiring (rep_id / outcome / source / days)
- Table rendering with score badges and outcome badges
- Pagination (page count, prev/next button visibility)
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _wire_supabase(mocker, *, calls=None, total=0, reps=None):
    """Stub the calls list query + reps dropdown query.

    The route's calls query chains a variable number of .eq() calls depending
    on which filters are set. To support every combination, build a chain
    where every method returns the chain itself and only .execute() returns
    data — this way the test doesn't care how many filter nodes the route adds.
    """
    fake_db = mocker.MagicMock()

    def _resp(data, count=None):
        m = mocker.MagicMock()
        m.data = data
        m.count = count
        return m

    def _self_chaining_mock(execute_result):
        chain = mocker.MagicMock()
        for method in ("select", "gte", "order", "eq", "range", "limit"):
            getattr(chain, method).return_value = chain
        chain.execute.return_value = execute_result
        return chain

    calls_chain = _self_chaining_mock(_resp(calls or [], count=total))
    reps_chain = _self_chaining_mock(_resp(reps or []))

    def _table(name):
        return reps_chain if name == "reps" else calls_chain

    fake_db.table.side_effect = _table
    mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)


def _row(**overrides):
    base = {
        "id": "call-1",
        "lead_name": "John Doe",
        "lead_source": "meta",
        "outcome": "sold",
        "called_at": "2026-04-30T15:42:00+00:00",
        "status": "scored",
        "rep_id": "rep-1",
        "reps": {"name": "Sarah"},
        "call_scores": [{"overall_score": 8, "therapist_mode_flag": False}],
    }
    base.update(overrides)
    return base


# ── Empty state ─────────────────────────────────────────────────────────────

class TestCallsListEmpty:
    def test_renders_empty_state(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0, reps=[])
        body = client.get("/ui/calls").text
        assert "No calls match these filters" in body

    def test_total_count_in_header(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0, reps=[])
        body = client.get("/ui/calls").text
        assert "0 calls" in body


# ── Populated table ─────────────────────────────────────────────────────────

class TestCallsListRendering:
    def test_table_renders_each_row(self, client, mocker):
        rows = [
            _row(id="c1", lead_name="Alice", reps={"name": "Sarah"}),
            _row(id="c2", lead_name="Bob",   reps={"name": "Mike"},
                 call_scores=[{"overall_score": 4, "therapist_mode_flag": True}]),
        ]
        _wire_supabase(mocker, calls=rows, total=2, reps=[])
        body = client.get("/ui/calls").text
        # Both leads appear
        assert "Alice" in body and "Bob" in body
        # Both reps appear
        assert "Sarah" in body and "Mike" in body
        # Both scores appear
        assert ">8<" in body and ">4<" in body
        # Therapist mode marker on Bob's row
        assert "🛑" in body

    def test_outcome_badge_label_visible(self, client, mocker):
        rows = [
            _row(id="c1", outcome="sold"),
            _row(id="c2", outcome="follow_up"),
            _row(id="c3", outcome="not_sold"),
        ]
        _wire_supabase(mocker, calls=rows, total=3, reps=[])
        body = client.get("/ui/calls").text
        assert "Sold" in body
        assert "Follow-up" in body
        assert "Not sold" in body

    def test_row_links_to_call_detail(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(id="abc-123")], total=1, reps=[])
        body = client.get("/ui/calls").text
        # The onclick handler navigates to the detail page
        assert "/ui/calls/abc-123" in body

    def test_called_at_formatted_compactly(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(called_at="2026-04-30T15:42:00+00:00")], total=1, reps=[])
        body = client.get("/ui/calls").text
        # The template trims the ISO string and replaces 'T' with a space
        assert "2026-04-30 15:42" in body


# ── Filter form ─────────────────────────────────────────────────────────────

class TestCallsListFilters:
    def test_reps_dropdown_populated(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0,
                       reps=[{"id": "r1", "name": "Sarah"}, {"id": "r2", "name": "Mike"}])
        body = client.get("/ui/calls").text
        assert 'value="r1"' in body and "Sarah" in body
        assert 'value="r2"' in body and "Mike" in body

    def test_selected_filter_persists_in_form(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0,
                       reps=[{"id": "r1", "name": "Sarah"}])
        body = client.get("/ui/calls?outcome=sold&days=7").text
        # Confirm the matching option got the selected attribute. The
        # easiest reliable signal is "selected" appearing immediately
        # before the human-readable label of the sold/7-day option.
        assert "selected>Sold</option>" in body
        assert "selected>7 days</option>" in body

    def test_reset_link_only_shows_when_filters_active(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0, reps=[])
        # No filters → no reset link
        body = client.get("/ui/calls").text
        assert ">Reset</a>" not in body
        # With filter → reset link shows
        body = client.get("/ui/calls?outcome=sold").text
        assert ">Reset</a>" in body


# ── Pagination ──────────────────────────────────────────────────────────────

class TestCallsListPagination:
    def test_no_pagination_when_total_fits_one_page(self, client, mocker):
        _wire_supabase(mocker, calls=[_row()], total=10, reps=[])
        body = client.get("/ui/calls").text
        # 10 calls < 25 per page → no pagination block
        assert "Page 1 of" not in body

    def test_pagination_visible_when_total_exceeds_per_page(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(id=f"c{i}") for i in range(25)],
                       total=60, reps=[])
        body = client.get("/ui/calls").text
        assert "Page 1 of 3" in body
        # Prev disabled on page 1
        assert "← Prev" in body
        # Next enabled
        assert "Next →" in body

    def test_filter_state_carried_in_pagination_links(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(id=f"c{i}") for i in range(25)],
                       total=60, reps=[])
        body = client.get("/ui/calls?outcome=sold&days=7").text
        # Pagination next link should preserve the filters
        assert "outcome=sold" in body
        assert "days=7" in body
        assert "page=2" in body


# ── Active nav highlight ────────────────────────────────────────────────────

def test_calls_list_marks_calls_as_active(client, mocker):
    _wire_supabase(mocker, calls=[], total=0, reps=[])
    body = client.get("/ui/calls").text
    assert 'font-medium">Calls' in body
