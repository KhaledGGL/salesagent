"""GHL source mapping — drives downstream attribution analytics.

If this misclassifies, every cohort report (meta vs google vs organic)
is wrong and RevOps decisions follow bad data.
"""

import pytest

from app.services.ghl_client import map_ghl_source


class TestMapGhlSource:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Facebook", "meta"),
            ("facebook lead ad", "meta"),
            ("FB Ads", "meta"),
            ("Instagram", "meta"),
            ("IG Story", "meta"),
            ("Meta Ads", "meta"),
            ("Google Ads", "google"),
            ("google search", "google"),
            ("Google AdWords Campaign", "google"),
            ("Organic", "organic"),
            ("Referral", "organic"),
            ("", "organic"),
            ("unknown_thing", "organic"),
        ],
    )
    def test_source_mapping(self, raw, expected):
        assert map_ghl_source(raw) == expected

    def test_none_input_defaults_to_organic(self):
        assert map_ghl_source(None) == "organic"

    def test_whitespace_handled(self):
        assert map_ghl_source("  Facebook  ") == "meta"

    def test_case_insensitive(self):
        assert map_ghl_source("GOOGLE ADS") == "google"
        assert map_ghl_source("FACEBOOK") == "meta"
