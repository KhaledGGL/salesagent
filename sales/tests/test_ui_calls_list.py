"""Tests for /ui/calls — multi-value filtering with include/exclude.

Coverage:
- Empty state when no calls match
- Multi-value filters (rep_id, outcome, source, utm_source, utm_medium)
- Include vs. exclude (op=in / op=not_in) per field
- Free-text 'contains' for utm_campaign / utm_content / utm_term
- Date range (start_date / end_date) overrides preset window
- Pagination preserves every active filter in the URL

Uses a self-chaining Supabase mock so tests don't restate which methods
are called in which order — only the .execute() result matters.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from sales.app.main import app
    return TestClient(app)


def _self_chaining(execute_data, count=None):
    """Chain mock where every chained call returns self; .execute() returns
    a response with the configured .data and .count."""
    chain = MagicMock()
    for method in ("select", "gte", "lte", "eq", "neq", "order", "range",
                   "limit", "maybe_single", "single", "filter", "in_", "ilike"):
        getattr(chain, method).return_value = chain
    # `.not_.is_(...)` needs `not_` to behave like an attribute that
    # returns the same chain so the subsequent .is_() is also self.
    chain.not_ = chain
    chain.is_ = MagicMock(return_value=chain)
    resp = MagicMock()
    resp.data = execute_data
    resp.count = count
    chain.execute.return_value = resp
    return chain


def _wire_supabase(mocker, *, calls=None, total=0, reps=None,
                   utm_sources=None, utm_mediums=None):
    fake_db = MagicMock()

    def _resp(data, count=None):
        m = MagicMock()
        m.data = data
        m.count = count
        return m

    calls_chain = _self_chaining(calls or [], count=total)
    reps_chain = _self_chaining(reps or [])
    distinct_chain_factory = {}

    # _distinct_text_values calls db.table("calls").select(col).not_.is_(...)...
    # We can't easily branch on the column from inside the chain; route shares
    # one chain for the main query AND the distincts. Use side_effect on
    # .table() to return DIFFERENT chains based on call order.
    distinct_utm_source = _self_chaining([{"utm_source": s} for s in (utm_sources or [])])
    distinct_utm_medium = _self_chaining([{"utm_medium": m} for m in (utm_mediums or [])])

    table_call_count = {"calls": 0}

    def _table(name):
        if name == "reps":
            return reps_chain
        if name == "calls":
            # Order matters: route calls .table("calls") three times —
            # first for utm_source distinct, second for utm_medium, third for the main query.
            table_call_count["calls"] += 1
            n = table_call_count["calls"]
            if n == 1:
                return distinct_utm_source
            if n == 2:
                return distinct_utm_medium
            return calls_chain
        return _self_chaining([])

    fake_db.table.side_effect = _table
    mocker.patch("sales.app.ui.routes.get_supabase", return_value=fake_db)
    return fake_db, calls_chain


def _row(**overrides):
    base = {
        "id": "call-1",
        "lead_name": "John Doe",
        "lead_source": "meta",
        "outcome": "sold",
        "called_at": "2026-04-30T15:42:00+00:00",
        "status": "scored",
        "rep_id": "rep-1",
        "utm_source": "facebook",
        "utm_campaign": "back-pain-q2-2026",
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


# ── Table rendering ─────────────────────────────────────────────────────────

class TestCallsListRendering:
    def test_table_renders_each_row(self, client, mocker):
        rows = [
            _row(id="c1", lead_name="Alice", reps={"name": "Sarah"}),
            _row(id="c2", lead_name="Bob",   reps={"name": "Mike"},
                 call_scores=[{"overall_score": 4, "therapist_mode_flag": True}]),
        ]
        _wire_supabase(mocker, calls=rows, total=2, reps=[])
        body = client.get("/ui/calls").text
        assert "Alice" in body and "Bob" in body
        assert "Sarah" in body and "Mike" in body
        assert ">8<" in body and ">4<" in body
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
        assert "/ui/calls/abc-123" in body

    def test_utm_campaign_column_rendered(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(utm_campaign="back-pain-q2-2026")], total=1, reps=[])
        body = client.get("/ui/calls").text
        assert "back-pain-q2-2026" in body


# ── Filter form ─────────────────────────────────────────────────────────────

class TestCallsListFilters:
    def test_reps_dropdown_populated(self, client, mocker):
        _wire_supabase(
            mocker, calls=[], total=0,
            reps=[{"id": "r1", "name": "Sarah"}, {"id": "r2", "name": "Mike"}],
        )
        body = client.get("/ui/calls").text
        assert 'value="r1"' in body and "Sarah" in body
        assert 'value="r2"' in body and "Mike" in body

    def test_utm_dropdowns_populated_from_distinct_values(self, client, mocker):
        _wire_supabase(
            mocker, calls=[], total=0, reps=[],
            utm_sources=["facebook", "google", "tiktok"],
            utm_mediums=["cpc", "social"],
        )
        body = client.get("/ui/calls").text
        for src in ("facebook", "google", "tiktok"):
            assert src in body
        for med in ("cpc", "social"):
            assert med in body

    def test_selected_multi_filter_marked_checked(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0,
                       reps=[{"id": "r1", "name": "Sarah"}])
        body = client.get("/ui/calls?outcome=sold&outcome=follow_up").text
        # Both selected outcome checkboxes should be checked
        assert 'value="sold" checked' in body
        assert 'value="follow_up" checked' in body

    def test_exclude_op_marked_in_radio(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0, reps=[])
        body = client.get("/ui/calls?outcome=sold&outcome_op=not_in").text
        # "Is not" radio for outcome should be checked
        assert 'name="outcome_op" value="not_in" checked' in body

    def test_reset_link_only_shows_when_filters_active(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0, reps=[])
        body = client.get("/ui/calls").text
        assert ">Reset all</a>" not in body

        body = client.get("/ui/calls?outcome=sold").text
        assert ">Reset all</a>" in body

    def test_free_text_filter_value_persists(self, client, mocker):
        _wire_supabase(mocker, calls=[], total=0, reps=[])
        body = client.get("/ui/calls?utm_campaign=back-pain").text
        assert 'value="back-pain"' in body


# ── Filter logic actually reaches the query builder ─────────────────────────

class TestCallsListFilterLogic:
    """Assert the right Supabase methods get called for each filter shape."""

    def test_in_filter_calls_in_method(self, client, mocker):
        _, calls_chain = _wire_supabase(mocker, calls=[], total=0, reps=[])
        client.get("/ui/calls?outcome=sold&outcome=follow_up")
        # in_("outcome", ["sold", "follow_up"]) was called somewhere on the chain
        in_calls = [c for c in calls_chain.in_.call_args_list
                    if c.args and c.args[0] == "outcome"]
        assert in_calls, "in_('outcome', ...) should have been called"
        assert set(in_calls[0].args[1]) == {"sold", "follow_up"}

    def test_not_in_filter_uses_filter_method(self, client, mocker):
        _, calls_chain = _wire_supabase(mocker, calls=[], total=0, reps=[])
        client.get("/ui/calls?outcome=sold&outcome_op=not_in")
        # filter("outcome", "not.in", "(sold)") was called
        filter_calls = [c for c in calls_chain.filter.call_args_list
                        if c.args and c.args[0] == "outcome"]
        assert filter_calls, "filter('outcome', 'not.in', ...) should have been called"
        assert filter_calls[0].args[1] == "not.in"

    def test_free_text_uses_ilike(self, client, mocker):
        _, calls_chain = _wire_supabase(mocker, calls=[], total=0, reps=[])
        client.get("/ui/calls?utm_campaign=back-pain")
        ilike_calls = [c for c in calls_chain.ilike.call_args_list
                       if c.args and c.args[0] == "utm_campaign"]
        assert ilike_calls, "ilike('utm_campaign', ...) should have been called"
        assert "back-pain" in ilike_calls[0].args[1]

    def test_explicit_dates_override_preset_window(self, client, mocker):
        _, calls_chain = _wire_supabase(mocker, calls=[], total=0, reps=[])
        client.get("/ui/calls?start_date=2026-01-01&end_date=2026-02-01&days=7")
        # Should call gte with the explicit start date, not a 7-day cutoff
        gte_calls = [c for c in calls_chain.gte.call_args_list
                     if c.args and c.args[0] == "called_at"]
        assert gte_calls
        # The first arg passed should be exactly our start_date
        assert "2026-01-01" in gte_calls[0].args[1]


# ── Pagination ──────────────────────────────────────────────────────────────

class TestCallsListPagination:
    def test_no_pagination_when_total_fits_one_page(self, client, mocker):
        _wire_supabase(mocker, calls=[_row()], total=10, reps=[])
        body = client.get("/ui/calls").text
        assert "Page 1 of" not in body

    def test_pagination_visible_when_total_exceeds_per_page(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(id=f"c{i}") for i in range(25)],
                       total=60, reps=[])
        body = client.get("/ui/calls").text
        assert "Page 1 of 3" in body

    def test_filter_state_carried_in_pagination_links(self, client, mocker):
        _wire_supabase(mocker, calls=[_row(id=f"c{i}") for i in range(25)],
                       total=60, reps=[])
        body = client.get("/ui/calls?outcome=sold&outcome_op=not_in&utm_campaign=q2").text
        # The 'Next →' link should preserve all filters
        assert "outcome=sold" in body
        assert "outcome_op=not_in" in body
        assert "utm_campaign=q2" in body
        assert "page=2" in body


# ── Active nav highlight ────────────────────────────────────────────────────

def test_calls_list_marks_calls_as_active(client, mocker):
    _wire_supabase(mocker, calls=[], total=0, reps=[])
    body = client.get("/ui/calls").text
    assert 'font-medium">Calls' in body
