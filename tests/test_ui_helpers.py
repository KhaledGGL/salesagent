"""Pure-function tests for the UI formatting helpers."""

import pytest

from app.ui import helpers as h


class TestScoreColorClass:
    def test_high_is_emerald(self):
        assert "emerald" in h.score_color_class(9)
        assert "emerald" in h.score_color_class(8)

    def test_mid_is_amber(self):
        assert "amber" in h.score_color_class(7)
        assert "amber" in h.score_color_class(5)

    def test_low_is_rose(self):
        assert "rose" in h.score_color_class(4)
        assert "rose" in h.score_color_class(1)

    def test_none_is_neutral(self):
        assert "zinc" in h.score_color_class(None)


class TestOutcome:
    def test_known_outcomes_have_distinct_classes(self):
        sold = h.outcome_badge_class("sold")
        not_sold = h.outcome_badge_class("not_sold")
        follow_up = h.outcome_badge_class("follow_up")
        assert sold != not_sold != follow_up
        assert "emerald" in sold
        assert "rose" in not_sold
        assert "amber" in follow_up

    def test_unknown_outcome_falls_back(self):
        cls = h.outcome_badge_class("anything-weird")
        assert "zinc" in cls

    @pytest.mark.parametrize("v,expected", [
        ("sold", "Sold"),
        ("not_sold", "Not sold"),
        ("follow_up", "Follow-up"),
        ("no_show", "No show"),
        ("rescheduled", "Rescheduled"),
        (None, "—"),
        ("unknown", "—"),
    ])
    def test_outcome_label(self, v, expected):
        assert h.outcome_label(v) == expected


class TestSeverityAndCategory:
    def test_severity_class_distinct_per_level(self):
        assert "rose" in h.severity_class("high")
        assert "amber" in h.severity_class("medium")
        assert "zinc" in h.severity_class("low")
        assert "zinc" in h.severity_class(None)

    def test_category_label_humanized(self):
        assert h.category_label("objection_handling") == "Objection Handling"
        assert h.category_label("diagnosis") == "Diagnosis"
        assert h.category_label(None) == "—"


class TestHandlingQuality:
    def test_distinct_classes_per_quality(self):
        assert "emerald" in h.handling_quality_class("excellent")
        assert "sky" in h.handling_quality_class("good")
        assert "amber" in h.handling_quality_class("fair")
        assert "rose" in h.handling_quality_class("poor")


class TestFormatters:
    @pytest.mark.parametrize("seconds,expected", [
        (0, "0:00"),
        (5, "0:05"),
        (60, "1:00"),
        (125, "2:05"),
        (3600, "60:00"),
        (None, "—"),
        (-1, "—"),
    ])
    def test_format_seconds_to_mmss(self, seconds, expected):
        assert h.format_seconds_to_mmss(seconds) == expected

    @pytest.mark.parametrize("conf,expected", [
        (0.92, "92%"),
        (1.0, "100%"),
        (0.0, "0%"),
        (None, None),
    ])
    def test_format_confidence_pct(self, conf, expected):
        assert h.format_confidence_pct(conf) == expected

    @pytest.mark.parametrize("seconds,expected", [
        (0, "0s"),
        (45, "45s"),
        (60, "1m 00s"),
        (387, "6m 27s"),
        (None, "—"),
    ])
    def test_format_duration_minutes(self, seconds, expected):
        assert h.format_duration_minutes(seconds) == expected
