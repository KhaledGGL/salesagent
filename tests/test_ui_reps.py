"""Tests for /ui/reps (list) and /ui/reps/:id (detail).

Covers:
- Reps list renders the v_rep_performance_30d shape
- Rep detail 404 when rep not found
- Rep detail renders stats, score trend, coaching effectiveness, recent calls
"""

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


# ── Reps list ───────────────────────────────────────────────────────────────

class TestRepsList:
    def test_empty(self, client, mocker):
        from unittest.mock import MagicMock
        fake_db = MagicMock()
        fake_db.table.return_value = _self_chaining([])
        mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)

        body = client.get("/ui/reps").text
        assert "No active reps yet" in body

    def test_renders_rows(self, client, mocker):
        from unittest.mock import MagicMock
        rows = [
            {"rep_id": "r1", "rep_name": "Sarah", "total_calls": 12,
             "sold_calls": 4, "close_rate_pct": 33.3, "avg_overall_score": 8.2,
             "therapist_mode_count": 0},
            {"rep_id": "r2", "rep_name": "Mike", "total_calls": 8,
             "sold_calls": 1, "close_rate_pct": 12.5, "avg_overall_score": 5.4,
             "therapist_mode_count": 2},
        ]
        fake_db = MagicMock()
        fake_db.table.return_value = _self_chaining(rows)
        mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)

        body = client.get("/ui/reps").text
        assert "Sarah" in body
        assert "Mike" in body
        assert "33.3%" in body
        assert "12.5%" in body
        # Therapist-mode flag rendered for Mike
        assert "🛑 2" in body
        # Click-row navigates to detail page
        assert "/ui/reps/r1" in body
        assert "/ui/reps/r2" in body


# ── Rep detail ──────────────────────────────────────────────────────────────

def _wire_rep_detail(mocker, *, rep=None, perf=None, calls=None, coaching=None):
    """Different tables return different shapes — mock per-table."""
    from unittest.mock import MagicMock
    fake_db = MagicMock()

    def _resp(data, count=None):
        m = MagicMock()
        m.data = data
        m.count = count
        return m

    def _table(name):
        if name == "reps":
            chain = MagicMock()
            chain.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(rep)
            return chain
        if name == "v_rep_performance_30d":
            return _self_chaining([perf] if perf else [])
        if name == "calls":
            return _self_chaining(calls or [])
        if name == "coaching_moments":
            return _self_chaining(coaching or [])
        return _self_chaining([])

    fake_db.table.side_effect = _table
    mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)


class TestRepDetail:
    def test_404_when_rep_missing(self, client, mocker):
        _wire_rep_detail(mocker, rep=None)
        r = client.get("/ui/reps/missing-rep")
        assert r.status_code == 404

    def test_renders_rep_header_and_stats(self, client, mocker):
        rep = {"id": "r1", "name": "Sarah Rivera", "email": "sarah@example.com",
               "is_active": True, "created_at": "2026-04-01T00:00:00Z"}
        perf = {"rep_id": "r1", "rep_name": "Sarah Rivera", "total_calls": 12,
                "sold_calls": 4, "close_rate_pct": 33.3, "avg_overall_score": 8.2,
                "avg_rapport": 7.5, "avg_diagnosis": 8.0, "avg_objection": 7.0,
                "avg_close": 9.0, "avg_compliance": 8.5, "therapist_mode_count": 0}
        _wire_rep_detail(mocker, rep=rep, perf=perf)
        body = client.get("/ui/reps/r1").text
        assert "Sarah Rivera" in body
        assert "sarah@example.com" in body
        assert "12 calls in last 30 days" in body
        assert "33.3%" in body

    def test_score_trend_present_when_calls_exist(self, client, mocker):
        rep = {"id": "r1", "name": "Sarah", "is_active": True, "created_at": "2026-04-01T00:00:00Z"}
        calls = [
            {"id": "c1", "lead_name": "John", "lead_source": "meta",
             "outcome": "sold", "called_at": "2026-04-20T15:00:00Z", "status": "scored",
             "call_scores": [{"overall_score": 8, "rapport_score": 7, "diagnosis_score": 8,
                              "objection_score": 6, "close_score": 9, "compliance_score": 8,
                              "therapist_mode_flag": False}]},
        ]
        _wire_rep_detail(mocker, rep=rep, perf=None, calls=calls)
        body = client.get("/ui/reps/r1").text
        # Chart canvas + trend section render when timeline non-empty
        assert "repScoreChart" in body
        assert "Recent calls" in body
        assert "John" in body

    def test_coaching_effectiveness_block_when_moments_exist(self, client, mocker):
        rep = {"id": "r1", "name": "Sarah", "is_active": True, "created_at": "2026-04-01T00:00:00Z"}
        # One scored call, plus a coaching moment in 'diagnosis' before that call
        calls = [
            {"id": "c1", "lead_name": "John", "lead_source": "meta",
             "outcome": "sold", "called_at": "2026-04-25T15:00:00Z", "status": "scored",
             "call_scores": [{"overall_score": 8, "rapport_score": 7, "diagnosis_score": 9,
                              "objection_score": 6, "close_score": 9, "compliance_score": 8,
                              "therapist_mode_flag": False}]},
        ]
        coaching = [
            {"id": "cm1", "category": "diagnosis", "severity": "medium",
             "note": "Skipped consequence question.", "timestamp_seconds": 200,
             "created_at": "2026-04-10T00:00:00Z",
             "calls": {"rep_id": "r1", "called_at": "2026-04-09T00:00:00Z"}},
        ]
        _wire_rep_detail(mocker, rep=rep, perf=None, calls=calls, coaching=coaching)
        body = client.get("/ui/reps/r1").text
        assert "Coaching effectiveness" in body
        assert "Diagnosis" in body
        assert "Skipped consequence" in body
