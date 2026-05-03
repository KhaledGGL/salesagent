"""Tests for the /ui/calls/:id route.

Mocks Supabase to cover three branches:
1. Happy path: scored call → full scorecard rendered
2. Unscored call: 'received'/'failed' status → partial state with banner
3. Not found: 404
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _scored_call_row():
    """A complete calls + reps + call_scores row mirroring the join shape."""
    return {
        "id": "call-uuid-1",
        "lead_name": "Sarah Johnson",
        "lead_source": "meta",
        "lead_temperature": "warm",
        "outcome": "sold",
        "transcript": "Rep: Hi Sarah... Prospect: Hi, yes I want to buy.",
        "duration_seconds": 387,
        "called_at": "2026-04-30T15:42:00+00:00",
        "recording_url": "https://example.com/rec.mp3",
        "status": "scored",
        "error_message": None,
        "reps": {"name": "Sarah Rivera"},
        "call_scores": [{
            "rapport_score": 8,
            "diagnosis_score": 7,
            "objection_score": 6,
            "close_score": 9,
            "compliance_score": 8,
            "overall_score": 8,
            "therapist_mode_flag": False,
            "therapist_mode_reason": None,
            "win_loss_timestamp": 645,
            "win_loss_description": "Prospect committed at 10:45 after pain question.",
            "ai_summary": "Strong close after solid diagnosis.",
            "outcome_confidence": 0.92,
            "outcome_evidence": "At ~22:14 prospect said 'yes charge the card'.",
        }],
    }


def _coaching_rows():
    return [
        {"timestamp_seconds": 320, "category": "diagnosis", "severity": "medium",
         "note": "Missed opportunity to ask about prior solutions tried."},
        {"timestamp_seconds": 540, "category": "objection_handling", "severity": "high",
         "note": "Glossed over the spouse objection."},
    ]


def _objection_rows():
    return [
        {"timestamp_seconds": 540, "objection_type": "spouse",
         "objection_text": "I need to talk to my husband first.",
         "handling_quality": "fair"},
    ]


def _wire_supabase(mocker, *, call_row, coaching=None, objections=None):
    """Stub the three table().select()...execute() calls the route makes."""
    fake_db = mocker.MagicMock()

    # Build a fake response object that exposes a .data attribute. Using a
    # MagicMock with the data attribute set directly (rather than as a dict)
    # because the route checks `call_resp.data` on the maybe_single() result.
    def _resp(data):
        m = mocker.MagicMock()
        m.data = data
        return m

    # The route calls three different tables; we differentiate by table name.
    def _table(name):
        t = mocker.MagicMock()
        if name == "calls":
            # .select(...).eq(...).maybe_single().execute() → resp(call_row)
            t.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = _resp(call_row)
        elif name == "coaching_moments":
            t.select.return_value.eq.return_value.order.return_value.execute.return_value = _resp(coaching or [])
        elif name == "call_objections":
            t.select.return_value.eq.return_value.order.return_value.execute.return_value = _resp(objections or [])
        return t

    fake_db.table.side_effect = _table
    mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)


# ── Happy path ──────────────────────────────────────────────────────────────

class TestCallDetailScored:
    def test_renders_rep_and_lead(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=_coaching_rows(), objections=_objection_rows())
        body = client.get("/ui/calls/call-uuid-1").text
        assert "Sarah Rivera" in body
        assert "Sarah Johnson" in body  # lead name
        assert "meta" in body

    def test_renders_overall_and_category_scores(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=_coaching_rows(), objections=_objection_rows())
        body = client.get("/ui/calls/call-uuid-1").text
        # Overall card shows 8 with "overall" label nearby
        assert "overall" in body.lower()
        assert ">8<" in body  # overall_score appears as a standalone number
        # Category labels rendered
        for label in ("Rapport", "Diagnosis", "Objection", "Close", "Compliance"):
            assert label in body

    def test_renders_outcome_with_confidence_and_evidence(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        assert "Sold" in body
        assert "92%" in body
        assert "charge the card" in body

    def test_renders_coaching_moments(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=_coaching_rows(), objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        assert "Coaching moments" in body
        assert "Missed opportunity" in body
        assert "spouse objection" in body
        # Severity labels rendered
        assert "High" in body
        assert "Medium" in body

    def test_renders_objections_with_handling_quality(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=[], objections=_objection_rows())
        body = client.get("/ui/calls/call-uuid-1").text
        assert "Objections" in body
        assert "talk to my husband" in body
        assert "Fair" in body  # handling quality
        assert "Spouse" in body

    def test_renders_transcript(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        assert "Transcript" in body
        assert "I want to buy" in body

    def test_renders_recording_link(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        assert "https://example.com/rec.mp3" in body
        assert "Listen" in body

    def test_therapist_banner_only_when_flagged(self, client, mocker):
        row = _scored_call_row()
        row["call_scores"][0]["therapist_mode_flag"] = True
        row["call_scores"][0]["therapist_mode_reason"] = "Rep talked 70% of the time."
        _wire_supabase(mocker, call_row=row, coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        assert "Therapist mode triggered" in body
        assert "Rep talked 70%" in body

    def test_active_nav_is_calls(self, client, mocker):
        _wire_supabase(mocker, call_row=_scored_call_row(),
                       coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        # Calls link should have the active highlight class
        assert 'font-medium">Calls' in body


# ── Unscored / failed call ──────────────────────────────────────────────────

class TestCallDetailUnscored:
    def test_unscored_call_shows_banner(self, client, mocker):
        row = _scored_call_row()
        row["call_scores"] = []        # not scored yet
        row["status"] = "failed"
        row["error_message"] = "Claude API rate limit"
        _wire_supabase(mocker, call_row=row, coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        assert "hasn't been scored yet" in body
        assert "failed" in body
        assert "Claude API rate limit" in body

    def test_unscored_call_does_not_render_score_grid(self, client, mocker):
        row = _scored_call_row()
        row["call_scores"] = []
        _wire_supabase(mocker, call_row=row, coaching=[], objections=[])
        body = client.get("/ui/calls/call-uuid-1").text
        # Category labels should be absent — only the unscored banner shows
        assert "Rapport" not in body
        assert "Diagnosis" not in body


# ── 404 path ────────────────────────────────────────────────────────────────

class TestCallDetailNotFound:
    def test_unknown_call_returns_404(self, client, mocker):
        # maybe_single returning None directly (supabase-py 2.28+ behavior)
        fake_db = mocker.MagicMock()
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = None
        mocker.patch("app.ui.routes.get_supabase", return_value=fake_db)

        r = client.get("/ui/calls/does-not-exist")
        assert r.status_code == 404
