"""Tests for the /ui/ dashboard landing page."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _self_chaining(execute_data, count=None):
    from unittest.mock import MagicMock
    chain = MagicMock()
    for method in ("select", "gte", "lte", "eq", "neq", "order", "range",
                   "limit", "maybe_single", "single"):
        getattr(chain, method).return_value = chain
    resp = MagicMock()
    resp.data = execute_data
    resp.count = count
    chain.execute.return_value = resp
    return chain


def _wire(mocker, *, overview=None, rep_perf=None, rep_30d=None,
          recent_calls=None, latest_reports=None):
    from unittest.mock import MagicMock
    fake_db = MagicMock()

    def _table(name):
        if name == "v_weekly_overview":
            return _self_chaining([overview] if overview else [])
        if name == "v_rep_performance_weekly":
            return _self_chaining(rep_perf or [])
        if name == "v_rep_performance_30d":
            return _self_chaining(rep_30d or [])
        if name == "calls":
            return _self_chaining(recent_calls or [])
        if name == "weekly_reports":
            # Each report-type query gets the matching latest row
            chain = MagicMock()
            def _eq_side_effect(field, value):
                rows = [r for r in (latest_reports or []) if r.get("report_type") == value][:1]
                return _self_chaining(rows)
            chain.select.return_value.eq = _eq_side_effect
            # Default if no .eq used
            chain.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return chain
        return _self_chaining([])

    fake_db.table.side_effect = _table
    mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)


class TestDashboard:
    def test_renders_kpi_cards(self, client, mocker):
        ov = {"week_start": "2026-04-27", "week_end": "2026-05-03",
              "total_calls": 42, "sold_calls": 12, "close_rate_pct": 28.6,
              "avg_overall_score": 7.4, "therapist_mode_count": 3}
        _wire(mocker, overview=ov)
        body = client.get("/ui/").text
        assert "2026-04-27" in body
        assert ">42<" in body  # total calls in big card
        assert ">12<" in body  # sold
        assert "28.6" in body  # close rate
        assert "7.4" in body  # avg score

    def test_renders_top_performers_with_3call_minimum(self, client, mocker):
        rep_perf = [
            {"rep_id": "r1", "rep_name": "Sarah", "total_calls": 5, "sold_calls": 3,
             "close_rate_pct": 60.0, "avg_overall_score": 8.5},
            {"rep_id": "r2", "rep_name": "Bob (low volume)", "total_calls": 2,
             "sold_calls": 2, "close_rate_pct": 100.0, "avg_overall_score": 9.5},
            {"rep_id": "r3", "rep_name": "Mike (struggling)", "total_calls": 6,
             "sold_calls": 0, "close_rate_pct": 0.0, "avg_overall_score": 4.0},
        ]
        _wire(mocker, rep_perf=rep_perf)
        body = client.get("/ui/").text
        # Sarah qualifies, Bob does NOT (only 2 calls)
        assert "Sarah" in body
        assert "Bob (low volume)" not in body
        # Mike qualifies and lands in needs-coaching
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
        # Should render dashboard with empty placeholders, not 500
        assert "Overview" in r.text
        assert "No calls yet." in r.text
