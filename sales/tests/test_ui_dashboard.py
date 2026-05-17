"""Tests for the /ui/ dashboard landing page."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from sales.app.main import app
    return TestClient(app)


def _self_chaining(execute_data, count=None):
    """Mock chain that absorbs every Supabase query-builder method and
    finally yields .execute() with the given rows."""
    from unittest.mock import MagicMock
    chain = MagicMock()
    for method in ("select", "gte", "gt", "lte", "lt", "eq", "neq",
                   "order", "range", "limit", "maybe_single", "single"):
        getattr(chain, method).return_value = chain
    resp = MagicMock()
    resp.data = execute_data
    resp.count = count
    chain.execute.return_value = resp
    return chain


def _wire(mocker, *, in_range_calls=None, reps=None, rep_30d=None,
          recent_calls=None, latest_reports=None):
    """Wire a fake Supabase client for the dashboard route.

    The dashboard issues two `db.table("calls")` queries: the first is
    the in-range aggregation (uses .gte/.lt), the second is the recent
    feed (uses .order/.limit). We hand them out in that order via an
    iterator so each test can specify both shapes independently.
    """
    from unittest.mock import MagicMock
    fake_db = MagicMock()
    calls_chains = iter([
        _self_chaining(in_range_calls or []),  # 1st: aggregation
        _self_chaining(recent_calls or []),    # 2nd: recent feed
    ])

    def _table(name):
        if name == "calls":
            return next(calls_chains)
        if name == "reps":
            return _self_chaining(reps or [])
        if name == "v_rep_performance_30d":
            return _self_chaining(rep_30d or [])
        if name == "weekly_reports":
            chain = MagicMock()

            def _eq_side_effect(field, value):
                rows = [r for r in (latest_reports or [])
                        if r.get("report_type") == value][:1]
                return _self_chaining(rows)
            chain.select.return_value.eq = _eq_side_effect
            chain.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return chain
        return _self_chaining([])

    fake_db.table.side_effect = _table
    mocker.patch("sales.app.ui.routes.get_supabase", return_value=fake_db)


class TestDashboard:
    def test_renders_kpi_cards_from_in_range_aggregation(self, client, mocker):
        # Two scored calls in window → totals should be aggregated live.
        in_range = [
            {"id": "c1", "status": "scored", "outcome": "sold", "rep_id": "r1",
             "call_scores": {"overall_score": 9, "therapist_mode_flag": False}},
            {"id": "c2", "status": "scored", "outcome": "not_sold", "rep_id": "r1",
             "call_scores": {"overall_score": 5, "therapist_mode_flag": True}},
        ]
        _wire(mocker, in_range_calls=in_range, reps=[{"id": "r1", "name": "Sarah"}])
        body = client.get("/ui/").text
        assert ">2<" in body            # total calls
        assert ">1<" in body            # sold
        assert "50.0" in body           # close rate
        assert "7.0" in body            # avg score
        assert "Last 7 days" in body    # default range label

    def test_range_param_changes_label(self, client, mocker):
        _wire(mocker)
        body = client.get("/ui/?range=this_month").text
        assert "This month" in body

    def test_invalid_range_falls_back_to_default(self, client, mocker):
        _wire(mocker)
        r = client.get("/ui/?range=garbage")
        assert r.status_code == 200
        assert "Last 7 days" in r.text

    def test_renders_top_performers_with_3call_minimum(self, client, mocker):
        # Sarah: 5 calls, 3 sold, scores avg ~8.5 — qualifies as top performer.
        # Bob: 2 calls — does NOT qualify (below 3-call threshold).
        # Mike: 6 calls, 0 sold, low scores — qualifies, lands in needs-coaching.
        def _scored(rep_id, outcome, score):
            return {"id": f"x{score}", "status": "scored", "outcome": outcome,
                    "rep_id": rep_id,
                    "call_scores": {"overall_score": score,
                                    "therapist_mode_flag": False}}
        in_range = (
            [_scored("r1", "sold", s) for s in (9, 9, 8)]
            + [_scored("r1", "not_sold", s) for s in (8, 9)]
            + [_scored("r2", "sold", 9), _scored("r2", "sold", 10)]   # Bob, only 2 calls
            + [_scored("r3", "not_sold", s) for s in (4, 4, 4, 5, 4, 3)]
        )
        reps = [
            {"id": "r1", "name": "Sarah"},
            {"id": "r2", "name": "Bob (low volume)"},
            {"id": "r3", "name": "Mike (struggling)"},
        ]
        _wire(mocker, in_range_calls=in_range, reps=reps)
        body = client.get("/ui/").text
        assert "Sarah" in body
        assert "Bob (low volume)" not in body
        assert "Mike (struggling)" in body

    def test_recent_calls_feed_links_to_detail(self, client, mocker):
        recent = [
            {"id": "call-abc", "lead_name": "Jane", "lead_source": "meta",
             "outcome": "sold", "called_at": "2026-04-30T15:00:00Z",
             "status": "scored",
             "reps": {"name": "Sarah"},
             "call_scores": [{"overall_score": 9, "therapist_mode_flag": False}]},
        ]
        _wire(mocker, recent_calls=recent)
        body = client.get("/ui/").text
        assert "/ui/calls/call-abc" in body
        assert "Jane" in body
        assert "Sarah" in body
        assert ">9<" in body

    def test_empty_state_when_no_data(self, client, mocker):
        _wire(mocker)  # all empty
        r = client.get("/ui/")
        assert r.status_code == 200
        assert "Overview" in r.text
        assert "No calls yet." in r.text


class TestResolveRange:
    """Unit-level tests for the range resolver — verify boundaries are
    correct and the half-open interval [start, end) is honored."""

    def test_default_is_last_7_days(self):
        from sales.app.ui.routes import _resolve_range
        s, e, label, sub = _resolve_range("anything-unknown")
        assert label == "Last 7 days"
        assert sub == "Rolling 7 days"

    def test_each_known_key_returns_distinct_label(self):
        from sales.app.ui.routes import _resolve_range, DASHBOARD_RANGES
        labels = {_resolve_range(k)[2] for k, _ in DASHBOARD_RANGES}
        assert len(labels) == len(DASHBOARD_RANGES)

    def test_last_week_ends_at_this_monday(self):
        from datetime import datetime, timezone
        from sales.app.ui.routes import _resolve_range
        s, e, _, _ = _resolve_range("last_week")
        end = datetime.fromisoformat(e)
        # End is exclusive — points at this week's Monday 00:00 UTC
        assert end.weekday() == 0
        assert end.hour == 0 and end.minute == 0
        # Start is exactly 7 days before end
        start = datetime.fromisoformat(s)
        assert (end - start).days == 7

    def test_last_month_starts_first_of_previous_month(self):
        from datetime import datetime, timezone
        from sales.app.ui.routes import _resolve_range
        s, e, _, _ = _resolve_range("last_month")
        start = datetime.fromisoformat(s)
        end = datetime.fromisoformat(e)
        assert start.day == 1
        assert end.day == 1
        # End is exactly the 1st of the current month (UTC)
        assert end.year == datetime.now(timezone.utc).year or end.year == start.year + 1
