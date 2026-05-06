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


class TestFirstOrDict:
    """Supabase embeds: list (one-to-many) vs dict (one-to-one with UNIQUE FK).
    The helper must normalize both to a single row or None — regression test
    for the 500 we hit in production where call_scores came back as a dict
    and `(call_scores or [{}])[0]` did dict[0] → KeyError: 0."""

    def test_dict_input_returned_as_is(self):
        d = {"overall_score": 8}
        assert h.first_or_dict(d) is d

    def test_list_input_returns_first(self):
        assert h.first_or_dict([{"overall_score": 8}, {"overall_score": 5}]) == {"overall_score": 8}

    def test_empty_list_returns_none(self):
        assert h.first_or_dict([]) is None

    def test_none_input_returns_none(self):
        assert h.first_or_dict(None) is None


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


class TestComputeOverviewFromRows:
    """Live KPI aggregation that replaces v_weekly_overview on the dashboard."""

    def test_empty_rows_yield_zero_totals_and_none_averages(self):
        ov = h.compute_overview_from_rows([])
        assert ov == {
            "total_calls": 0, "sold_calls": 0,
            "close_rate_pct": None, "avg_overall_score": None,
            "therapist_mode_count": 0,
        }

    def test_only_scored_rows_count(self):
        rows = [
            # Two scored, mixed outcomes
            {"status": "scored", "outcome": "sold",
             "call_scores": {"overall_score": 9, "therapist_mode_flag": False}},
            {"status": "scored", "outcome": "not_sold",
             "call_scores": {"overall_score": 5, "therapist_mode_flag": True}},
            # Pending — should be ignored entirely
            {"status": "pending", "outcome": "sold",
             "call_scores": None},
        ]
        ov = h.compute_overview_from_rows(rows)
        assert ov["total_calls"] == 2
        assert ov["sold_calls"] == 1
        assert ov["close_rate_pct"] == 50.0
        assert ov["avg_overall_score"] == 7.0
        assert ov["therapist_mode_count"] == 1

    def test_handles_list_shaped_call_scores_embed(self):
        # PostgREST sometimes embeds the score as a list — first_or_dict
        # normalizes it
        rows = [
            {"status": "scored", "outcome": "sold",
             "call_scores": [{"overall_score": 8, "therapist_mode_flag": False}]},
        ]
        assert h.compute_overview_from_rows(rows)["avg_overall_score"] == 8.0


class TestComputeRepPerfFromRows:
    def test_groups_by_rep_and_resolves_names(self):
        rows = [
            {"status": "scored", "outcome": "sold", "rep_id": "r1",
             "call_scores": {"overall_score": 9, "therapist_mode_flag": False}},
            {"status": "scored", "outcome": "not_sold", "rep_id": "r1",
             "call_scores": {"overall_score": 7, "therapist_mode_flag": False}},
            {"status": "scored", "outcome": "sold", "rep_id": "r2",
             "call_scores": {"overall_score": 6, "therapist_mode_flag": True}},
        ]
        out = h.compute_rep_perf_from_rows(rows, {"r1": "Sarah", "r2": "Mike"})
        by_id = {r["rep_id"]: r for r in out}
        assert by_id["r1"]["rep_name"] == "Sarah"
        assert by_id["r1"]["total_calls"] == 2
        assert by_id["r1"]["sold_calls"] == 1
        assert by_id["r1"]["close_rate_pct"] == 50.0
        assert by_id["r1"]["avg_overall_score"] == 8.0
        assert by_id["r2"]["therapist_mode_count"] == 1

    def test_unknown_rep_falls_back_to_unknown_label(self):
        rows = [{"status": "scored", "outcome": "sold", "rep_id": "ghost",
                 "call_scores": {"overall_score": 7}}]
        out = h.compute_rep_perf_from_rows(rows, {})
        assert out[0]["rep_name"] == "Unknown"

    def test_skips_pending_and_missing_rep(self):
        rows = [
            {"status": "pending", "rep_id": "r1", "outcome": "sold", "call_scores": None},
            {"status": "scored", "rep_id": None, "outcome": "sold",
             "call_scores": {"overall_score": 9}},
        ]
        assert h.compute_rep_perf_from_rows(rows, {"r1": "Sarah"}) == []
