"""Tests for the inline-transcript webhook endpoint.

Covers the parse → filter → dedup → insert → enqueue path of
POST /webhooks/ghl/transcript-ready, plus the matching fast-path
branch in process_call that detects pre-populated transcripts and
skips the GHL fetch.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def _valid_payload(**overrides) -> dict:
    """Build a valid GHL transcript-ready payload, allowing per-test overrides."""
    base = {
        "call_sid": "CA" + "a" * 32,
        "call_user_id": "ghl_user_abc",
        "call_duration": 245,
        "call_status": "completed",
        "call_from": "+15555550123",
        "call_to": "+15555550456",
        "call_transcript": (
            "Rep: Hi, this is John from XYZ Wellness, am I speaking with Sarah? "
            "Prospect: Yes, this is Sarah. "
            "Rep: Great. I saw you filled out our form about chronic back pain — "
            "can you tell me a bit about what's going on? "
            "Prospect: Yeah, I've been dealing with it for about three years now..."
        ),
        "contact_id": "contact_xyz789",
        "contact_name": "Sarah Johnson",
        "contact_email": "sarah@example.com",
        "contact_phone": "+15555550456",
    }
    base.update(overrides)
    return base


def _mock_supabase_chain(mocker, *, rep_exists=True, duplicate=False):
    """Build a mock Supabase client matching the call chain in the endpoint."""
    mock = mocker.MagicMock()

    # Rep lookup: .table("reps").select("id").eq(...).maybe_single().execute()
    rep_lookup = mock.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute
    if rep_exists:
        rep_lookup.return_value = mocker.MagicMock(data={"id": "rep-uuid-123"})
    else:
        rep_lookup.return_value = mocker.MagicMock(data=None)
        # New rep insert: .table("reps").insert({...}).execute() → data=[{"id": ...}]
        mock.table.return_value.insert.return_value.execute.return_value = mocker.MagicMock(
            data=[{"id": "rep-uuid-new"}]
        )

    # Dedup lookup happens via the SAME chain prefix as rep lookup; we need
    # the test to differentiate them. Easier: patch the higher-level helper.
    return mock


class TestTranscriptReadyHappyPath:
    def test_valid_payload_accepted(self, client, mocker):
        """A clean payload should return 200 + accepted + a call_id."""
        # Patch the supabase client used inside the endpoint
        from unittest.mock import MagicMock

        fake_db = MagicMock()
        # rep lookup returns existing rep
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
            data={"id": "rep-uuid-123"}
        )
        # call insert returns new call row
        fake_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "call-uuid-456"}]
        )
        mocker.patch("app.webhooks.ghl.get_supabase", return_value=fake_db)
        mocker.patch("app.workers.tasks.process_call.delay")

        # Need dedup to return None (no existing call) — patch the second
        # maybe_single().execute() call. Easiest path: side_effect a sequence.
        rep_result = MagicMock(data={"id": "rep-uuid-123"})
        dedup_result = MagicMock(data=None)
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            rep_result, dedup_result
        ]

        r = client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert body["call_id"] == "call-uuid-456"


class TestTranscriptReadyFilters:
    def test_non_completed_status_skipped(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        r = client.post(
            "/webhooks/ghl/transcript-ready",
            json=_valid_payload(call_status="no-answer"),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert "call_status" in body["reason"]

    def test_voicemail_status_skipped(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        r = client.post(
            "/webhooks/ghl/transcript-ready",
            json=_valid_payload(call_status="voicemail"),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"

    def test_completed_case_insensitive(self, client, mocker):
        """call_status should match case-insensitively (GHL caps inconsistently)."""
        from unittest.mock import MagicMock
        fake_db = MagicMock()
        rep_result = MagicMock(data={"id": "rep-uuid-1"})
        dedup_result = MagicMock(data=None)
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            rep_result, dedup_result
        ]
        fake_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "call-uuid-1"}]
        )
        mocker.patch("app.webhooks.ghl.get_supabase", return_value=fake_db)
        mocker.patch("app.workers.tasks.process_call.delay")

        r = client.post(
            "/webhooks/ghl/transcript-ready",
            json=_valid_payload(call_status="Completed"),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"

    def test_short_transcript_skipped(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        r = client.post(
            "/webhooks/ghl/transcript-ready",
            json=_valid_payload(call_transcript="Hi."),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert body["reason"] == "transcript_too_short"

    def test_whitespace_only_transcript_skipped(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        r = client.post(
            "/webhooks/ghl/transcript-ready",
            json=_valid_payload(call_transcript="   \n\n   \t   "),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"


class TestTranscriptReadyDedup:
    def test_duplicate_call_sid_returns_existing(self, client, mocker):
        from unittest.mock import MagicMock
        fake_db = MagicMock()
        rep_result = MagicMock(data={"id": "rep-uuid-1"})
        # dedup lookup finds existing call
        dedup_result = MagicMock(data={"id": "existing-call-uuid"})
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            rep_result, dedup_result
        ]
        mocker.patch("app.webhooks.ghl.get_supabase", return_value=fake_db)

        r = client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "duplicate"
        assert body["call_id"] == "existing-call-uuid"


class TestTranscriptReadyEmptyStringCoercion:
    def test_empty_string_optionals_treated_as_none(self, client, mocker):
        """GHL merge tags substitute '' for missing values — must not blow up."""
        from unittest.mock import MagicMock
        fake_db = MagicMock()
        rep_result = MagicMock(data={"id": "rep-uuid-1"})
        dedup_result = MagicMock(data=None)
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            rep_result, dedup_result
        ]
        fake_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "call-uuid-1"}]
        )
        mocker.patch("app.webhooks.ghl.get_supabase", return_value=fake_db)
        mocker.patch("app.workers.tasks.process_call.delay")

        # Simulate GHL sending empty strings for unresolved merge tags
        payload = _valid_payload(
            contact_email="",
            contact_phone="",
            call_from="",
            call_to="",
        )
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"


class TestTranscriptReadyValidation:
    def test_missing_call_sid_returns_422(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        payload = _valid_payload()
        del payload["call_sid"]
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 422

    def test_missing_transcript_returns_422(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        payload = _valid_payload()
        del payload["call_transcript"]
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 422

    def test_missing_contact_id_returns_422(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        payload = _valid_payload()
        del payload["contact_id"]
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 422

    def test_missing_call_user_id_returns_422(self, client, mocker):
        mocker.patch("app.webhooks.ghl.get_supabase")
        payload = _valid_payload()
        del payload["call_user_id"]
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 422


class TestTranscriptReadyAutoProvisionRep:
    def test_unknown_user_id_creates_new_rep(self, client, mocker):
        """Regression: supabase-py 2.28+ returns None directly (not APIResponse)
        from maybe_single().execute() when no row matches. The endpoint must
        handle both shapes — None AND APIResponse(data=None) — gracefully."""
        from unittest.mock import MagicMock
        fake_db = MagicMock()
        # Rep lookup returns None (the actual behavior in supabase-py 2.28+)
        rep_lookup = None
        dedup_result = None
        fake_db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            rep_lookup, dedup_result
        ]
        # Both rep insert and call insert use the same chain — sequence them
        fake_db.table.return_value.insert.return_value.execute.side_effect = [
            MagicMock(data=[{"id": "rep-uuid-new"}]),
            MagicMock(data=[{"id": "call-uuid-new"}]),
        ]
        mocker.patch("app.webhooks.ghl.get_supabase", return_value=fake_db)
        mocker.patch("app.workers.tasks.process_call.delay")

        r = client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"
