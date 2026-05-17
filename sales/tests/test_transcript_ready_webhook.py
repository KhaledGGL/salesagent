"""Tests for the inline-transcript webhook endpoint.

Covers parse → filter → dedup → enrich → insert → enqueue path of
POST /webhooks/ghl/transcript-ready, plus the UTM-based attribution
and DB-derived lead_temperature that replaced the legacy GHL Contacts
API enrichment.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from sales.app.main import app
    return TestClient(app)


def _valid_payload(**overrides) -> dict:
    base = {
        "call_sid": "CA" + "a" * 32,
        "call_user_id": "ghl_user_abc",
        "call_user_name": "Sarah Rivera",
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


def _wire_supabase(
    mocker,
    *,
    rep=None,                   # existing rep row (or None to auto-provision)
    duplicate=False,            # whether the call_sid is already in the DB
    prior_calls_for_contact=0,  # used by lead_temperature compute
):
    """Build a fake Supabase client matching every chain the webhook uses."""
    fake_db = MagicMock()

    # ── Rep lookup chain ───────────────────────────────────────────────
    rep_chain = MagicMock()
    rep_chain.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        MagicMock(data=rep) if rep else None
    )
    # Rep insert (auto-provision path) — and possible name backfill update
    rep_chain.insert.return_value.execute.return_value = MagicMock(data=[{"id": "rep-uuid-new"}])
    rep_chain.update.return_value.eq.return_value.execute.return_value = MagicMock(data=None)

    # ── Calls dedup chain ─────────────────────────────────────────────
    calls_chain = MagicMock()
    if duplicate:
        calls_chain.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
            MagicMock(data={"id": "existing-call-uuid"})
        )
    else:
        calls_chain.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
            MagicMock(data=None)
        )
    # Lead-temperature compute: select("id").eq("ghl_contact_id", ...).limit(1).execute()
    calls_chain.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": f"prior-{i}"} for i in range(prior_calls_for_contact)]
    )
    # Call insert
    calls_chain.insert.return_value.execute.return_value = MagicMock(
        data=[{"id": "call-uuid-new"}]
    )

    def _table(name):
        if name == "reps":
            return rep_chain
        if name == "calls":
            return calls_chain
        return MagicMock()

    fake_db.table.side_effect = _table
    mocker.patch("sales.app.webhooks.ghl.get_supabase", return_value=fake_db)
    return fake_db


# ── Happy path ──────────────────────────────────────────────────────────────

class TestTranscriptReadyHappyPath:
    def test_valid_payload_accepted(self, client, mocker):
        _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        mocker.patch("sales.app.workers.tasks.score_call.delay")

        r = client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert body["call_id"] == "call-uuid-new"

    def test_score_call_enqueued(self, client, mocker):
        """Webhook enqueues score_call directly — no process_call hop anymore."""
        _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        score_call_delay = mocker.patch("sales.app.workers.tasks.score_call.delay")

        client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        score_call_delay.assert_called_once_with("call-uuid-new")


# ── Status / transcript filters ─────────────────────────────────────────────

class TestTranscriptReadyFilters:
    def test_non_completed_status_skipped(self, client, mocker):
        mocker.patch("sales.app.webhooks.ghl.get_supabase")
        r = client.post("/webhooks/ghl/transcript-ready",
                        json=_valid_payload(call_status="no-answer"))
        assert r.status_code == 200 and r.json()["status"] == "skipped"

    def test_completed_case_insensitive(self, client, mocker):
        _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        mocker.patch("sales.app.workers.tasks.score_call.delay")
        r = client.post("/webhooks/ghl/transcript-ready",
                        json=_valid_payload(call_status="Completed"))
        assert r.status_code == 200 and r.json()["status"] == "accepted"

    def test_short_transcript_skipped(self, client, mocker):
        mocker.patch("sales.app.webhooks.ghl.get_supabase")
        r = client.post("/webhooks/ghl/transcript-ready",
                        json=_valid_payload(call_transcript="Hi."))
        assert r.json()["reason"] == "transcript_too_short"


# ── Dedup ───────────────────────────────────────────────────────────────────

class TestTranscriptReadyDedup:
    def test_duplicate_call_sid_returns_existing(self, client, mocker):
        _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"}, duplicate=True)
        r = client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        body = r.json()
        assert body["status"] == "duplicate"
        assert body["call_id"] == "existing-call-uuid"


# ── Empty-string coercion ──────────────────────────────────────────────────

class TestTranscriptReadyEmptyStringCoercion:
    def test_empty_string_optionals_treated_as_none(self, client, mocker):
        _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        mocker.patch("sales.app.workers.tasks.score_call.delay")
        payload = _valid_payload(contact_email="", contact_phone="",
                                  call_from="", call_to="",
                                  utm_source="", utm_campaign="")
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 200 and r.json()["status"] == "accepted"


# ── Validation ──────────────────────────────────────────────────────────────

class TestTranscriptReadyValidation:
    @pytest.mark.parametrize("missing", ["call_sid", "call_transcript", "contact_id", "call_user_id"])
    def test_required_field_missing_returns_422(self, client, mocker, missing):
        mocker.patch("sales.app.webhooks.ghl.get_supabase")
        payload = _valid_payload()
        del payload[missing]
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 422


# ── Auto-provision rep ──────────────────────────────────────────────────────

class TestTranscriptReadyAutoProvisionRep:
    def test_unknown_user_id_creates_new_rep(self, client, mocker):
        # rep=None → maybe_single() returns None; webhook should insert a new rep
        _wire_supabase(mocker, rep=None)
        mocker.patch("sales.app.workers.tasks.score_call.delay")
        r = client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        assert r.status_code == 200 and r.json()["status"] == "accepted"


# ── UTM-based enrichment ────────────────────────────────────────────────────

class TestUtmEnrichment:
    def _captured_insert(self, fake_db):
        """Return the dict passed to .table('calls').insert(...)."""
        # The webhook calls `db.table("calls").insert({...}).execute()`
        # Our mock's calls_chain.insert was called once.
        calls_chain = fake_db.table.side_effect("calls")
        return calls_chain.insert.call_args[0][0]

    def test_utm_fields_persisted_to_call_row(self, client, mocker):
        fake_db = _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        mocker.patch("sales.app.workers.tasks.score_call.delay")

        payload = _valid_payload(
            utm_source="facebook",
            utm_medium="cpc",
            utm_campaign="back-pain-q2-2026",
            utm_content="video-ad-3",
            utm_term="lower back pain treatment",
        )
        r = client.post("/webhooks/ghl/transcript-ready", json=payload)
        assert r.status_code == 200

        row = self._captured_insert(fake_db)
        assert row["utm_source"]   == "facebook"
        assert row["utm_medium"]   == "cpc"
        assert row["utm_campaign"] == "back-pain-q2-2026"
        assert row["utm_content"]  == "video-ad-3"
        assert row["utm_term"]     == "lower back pain treatment"

    @pytest.mark.parametrize("utm,expected_lead_source", [
        ("facebook",   "meta"),
        ("Facebook",   "meta"),
        ("instagram",  "meta"),
        ("fb",         "meta"),
        ("meta-cpc",   "meta"),
        ("google",     "google"),
        ("google-ads", "google"),
        ("adwords",    "google"),
        ("youtube",    "google"),
        ("tiktok",     "organic"),
        ("direct",     "organic"),
        ("",           None),
    ])
    def test_utm_source_normalized_to_lead_source_enum(self, client, mocker, utm, expected_lead_source):
        fake_db = _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        mocker.patch("sales.app.workers.tasks.score_call.delay")

        client.post("/webhooks/ghl/transcript-ready",
                    json=_valid_payload(utm_source=utm))

        row = self._captured_insert(fake_db)
        assert row["lead_source"] == expected_lead_source

    def test_no_utm_yields_null_lead_source(self, client, mocker):
        fake_db = _wire_supabase(mocker, rep={"id": "rep-1", "name": "Sarah Rivera"})
        mocker.patch("sales.app.workers.tasks.score_call.delay")

        client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        row = self._captured_insert(fake_db)
        assert row["lead_source"] is None
        assert row["utm_source"] is None


# ── Lead temperature from our DB ────────────────────────────────────────────

class TestLeadTemperatureFromDB:
    def _captured_insert(self, fake_db):
        return fake_db.table.side_effect("calls").insert.call_args[0][0]

    def test_first_call_is_cold(self, client, mocker):
        fake_db = _wire_supabase(
            mocker, rep={"id": "rep-1", "name": "Sarah Rivera"},
            prior_calls_for_contact=0,
        )
        mocker.patch("sales.app.workers.tasks.score_call.delay")

        client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        row = self._captured_insert(fake_db)
        assert row["lead_temperature"] == "cold"

    def test_repeat_contact_is_warm(self, client, mocker):
        fake_db = _wire_supabase(
            mocker, rep={"id": "rep-1", "name": "Sarah Rivera"},
            prior_calls_for_contact=2,
        )
        mocker.patch("sales.app.workers.tasks.score_call.delay")

        client.post("/webhooks/ghl/transcript-ready", json=_valid_payload())
        row = self._captured_insert(fake_db)
        assert row["lead_temperature"] == "warm"
