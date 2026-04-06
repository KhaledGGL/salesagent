"""Pure-function tests for the lead enrichment helpers inside tasks.py.

Kept as pure functions precisely so they can be unit-tested without
Celery, Supabase, or GHL dependencies.
"""

from datetime import datetime, timedelta, timezone

from app.workers.tasks import _custom_field, _derive_lead_temperature, _enrich_from_contact


class TestDeriveLeadTemperature:
    def test_warm_when_contact_is_old(self):
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        assert _derive_lead_temperature({"dateAdded": old}) == "warm"

    def test_cold_when_contact_is_recent(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        assert _derive_lead_temperature({"dateAdded": recent}) == "cold"

    def test_cold_when_missing_date(self):
        assert _derive_lead_temperature({}) == "cold"

    def test_cold_on_invalid_date(self):
        assert _derive_lead_temperature({"dateAdded": "not-a-date"}) == "cold"

    def test_handles_z_suffix(self):
        old = "2024-01-01T00:00:00Z"
        assert _derive_lead_temperature({"dateAdded": old}) == "warm"


class TestCustomField:
    def test_dict_shape(self):
        contact = {"customFields": {"call_type": "Discovery"}}
        assert _custom_field(contact, "call_type", "default") == "discovery"

    def test_list_shape_by_key(self):
        contact = {"customFields": [{"key": "call_type", "value": "Treatment_Plan"}]}
        assert _custom_field(contact, "call_type", "default") == "treatment_plan"

    def test_list_shape_by_id(self):
        contact = {"customFields": [{"id": "cf_123", "value": "Sold"}]}
        assert _custom_field(contact, "cf_123", "default") == "sold"

    def test_missing_key_returns_default(self):
        contact = {"customFields": {}}
        assert _custom_field(contact, "call_type", "discovery") == "discovery"

    def test_missing_custom_fields_returns_default(self):
        assert _custom_field({}, "call_type", "discovery") == "discovery"

    def test_snake_case_alias(self):
        contact = {"custom_fields": {"call_type": "Discovery"}}
        assert _custom_field(contact, "call_type", "default") == "discovery"


class TestEnrichFromContact:
    def test_full_enrichment(self):
        old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        contact = {
            "firstName": "Jane",
            "lastName": "Doe",
            "source": "Facebook Lead Ad",
            "dateAdded": old,
            "customFields": {"call_type": "discovery", "call_outcome": "sold"},
        }
        result = _enrich_from_contact(contact)
        assert result["lead_name"] == "Jane Doe"
        assert result["lead_source"] == "meta"
        assert result["lead_temperature"] == "warm"
        assert result["call_type"] == "discovery"
        assert result["outcome"] == "sold"

    def test_lead_name_fallback_to_name_field(self):
        contact = {"name": "Jane Doe"}
        assert _enrich_from_contact(contact)["lead_name"] == "Jane Doe"

    def test_missing_name_returns_none(self):
        assert _enrich_from_contact({})["lead_name"] is None

    def test_only_first_name(self):
        assert _enrich_from_contact({"firstName": "Jane"})["lead_name"] == "Jane"
