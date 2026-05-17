"""Weekly report Block Kit regression tests.

These guard the exact failure modes that would cause a silent or
wrong report to land in the sales team's channel every Monday morning.
"""

import json

from sales.app.core.report_blocks import (
    TOP_N,
    _pct,
    _score_emoji,
    build_weekly_fallback_text,
    build_weekly_report_blocks,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _as_text(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)


def _overview(total=100, sold=25, close=25.0, avg=7.5, therapist=2):
    return {
        "week_start": "2026-03-30",
        "week_end": "2026-04-05",
        "total_calls": total,
        "sold_calls": sold,
        "close_rate_pct": close,
        "avg_overall_score": avg,
        "therapist_mode_count": therapist,
    }


def _rep(name, total=10, sold=3, close=30.0, avg=7.0, **extra):
    return {
        "rep_id": f"id-{name}",
        "rep_name": name,
        "total_calls": total,
        "sold_calls": sold,
        "close_rate_pct": close,
        "avg_overall_score": avg,
        **extra,
    }


# ── Tiny helper tests ────────────────────────────────────────────────────────

class TestFormatters:
    def test_score_emoji_none(self):
        assert _score_emoji(None) == "•"

    def test_score_emoji_green(self):
        assert _score_emoji(8.5) == "🟢"

    def test_score_emoji_yellow(self):
        assert _score_emoji(6.0) == "🟡"

    def test_score_emoji_red(self):
        assert _score_emoji(4.0) == "🔴"

    def test_pct_none(self):
        assert _pct(None) == "—"

    def test_pct_formats(self):
        assert _pct(25.0) == "25.0%"
        assert _pct(25.456) == "25.5%"


# ── Empty week ───────────────────────────────────────────────────────────────

class TestEmptyWeek:
    def test_zero_calls_short_circuits(self):
        blocks = build_weekly_report_blocks(
            week_start="2026-03-30",
            week_end="2026-04-05",
            overview={"total_calls": 0},
            rep_performance=[],
            top_objections=[],
        )
        text = _as_text(blocks)
        assert "No scored calls" in text
        assert "Top Performers" not in text
        assert "Needs Coaching" not in text

    def test_empty_overview_dict(self):
        blocks = build_weekly_report_blocks(
            week_start="2026-03-30",
            week_end="2026-04-05",
            overview={},
            rep_performance=[],
            top_objections=[],
        )
        assert "No scored calls" in _as_text(blocks)


# ── Populated report ─────────────────────────────────────────────────────────

class TestPopulatedReport:
    def _build(self, **kwargs):
        defaults = dict(
            week_start="2026-03-30",
            week_end="2026-04-05",
            overview=_overview(),
            rep_performance=[
                _rep("Sarah", total=10, sold=5, close=50.0, avg=8.5),
                _rep("Mike", total=12, sold=4, close=33.3, avg=7.0),
                _rep("Jamie", total=8, sold=2, close=25.0, avg=6.5),
                _rep("Alex", total=15, sold=2, close=13.3, avg=5.5),
                _rep("Chris", total=9, sold=1, close=11.1, avg=6.0),
            ],
            top_objections=[
                {"objection_type": "price", "lead_source": "meta",
                 "frequency": 12, "pct_of_total": 30.0},
                {"objection_type": "time", "lead_source": "google",
                 "frequency": 8, "pct_of_total": 20.0},
                {"objection_type": "spouse", "lead_source": "meta",
                 "frequency": 5, "pct_of_total": 12.5},
            ],
        )
        defaults.update(kwargs)
        return build_weekly_report_blocks(**defaults)

    def test_header_contains_date_range(self):
        text = _as_text(self._build())
        assert "2026-03-30" in text
        assert "2026-04-05" in text

    def test_overview_totals_present(self):
        text = _as_text(self._build())
        assert "100" in text  # total_calls
        assert "25" in text   # sold_calls
        assert "25.0%" in text

    def test_therapist_banner_when_nonzero(self):
        text = _as_text(self._build())
        assert "Therapist mode triggered 2" in text

    def test_therapist_banner_absent_when_zero(self):
        text = _as_text(self._build(overview=_overview(therapist=0)))
        assert "Therapist mode triggered" not in text

    def test_top_performers_ranked_by_close_rate(self):
        text = _as_text(self._build())
        # Sarah (50%) should appear before Mike (33%)
        assert text.index("Sarah") < text.index("Mike")

    def test_needs_coaching_ranked_by_lowest_score(self):
        text = _as_text(self._build())
        # Alex (5.5 avg) should appear in coaching section before Chris (6.0)
        coaching_idx = text.index("Needs Coaching")
        after_coaching = text[coaching_idx:]
        assert after_coaching.index("Alex") < after_coaching.index("Chris")

    def test_top_n_truncation_performers(self):
        # 10 reps with distinct close rates and matching avg scores so
        # sort order is unambiguous in both buckets.
        reps = [
            _rep(f"Rep{i}", total=5, close=100 - (i * 10), avg=10 - i)
            for i in range(10)
        ]
        text = _as_text(self._build(rep_performance=reps))

        perf_section = text[text.index("Top Performers"):text.index("Needs Coaching")]
        # Exactly TOP_N ranks (1., 2., 3.) — no 4.
        assert "1." in perf_section
        assert f"{TOP_N}." in perf_section
        assert f"{TOP_N + 1}." not in perf_section

        # Top performer is Rep0 (highest close rate), lowest-rank in the
        # top performers section is Rep(TOP_N-1).
        assert "Rep0" in perf_section
        assert f"Rep{TOP_N}" not in perf_section

    def test_excludes_reps_with_under_3_calls(self):
        text = _as_text(self._build(rep_performance=[
            _rep("LowVolume", total=2, close=100.0, avg=10.0),
            _rep("Qualified", total=5, close=40.0, avg=7.0),
        ]))
        # LowVolume had 2 calls → should be excluded despite 100% close rate
        assert "LowVolume" not in text
        assert "Qualified" in text

    def test_objections_rendered(self):
        text = _as_text(self._build())
        assert "price" in text
        assert "time" in text
        assert "spouse" in text
        assert "meta" in text
        assert "google" in text

    def test_objections_top_n_enforced(self):
        many = [
            {"objection_type": f"type{i}", "lead_source": "meta",
             "frequency": 10 - i, "pct_of_total": 10.0}
            for i in range(10)
        ]
        text = _as_text(self._build(top_objections=many))
        # Only TOP_N objections rendered in the section
        obj_section = text[text.index("Top Objections"):]
        # type0..type(TOP_N-1) should be present, beyond that should not
        for i in range(TOP_N):
            assert f"type{i}" in obj_section
        assert f"type{TOP_N}" not in obj_section


# ── Edge cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_none_close_rate_renders_dash(self):
        blocks = build_weekly_report_blocks(
            week_start="2026-03-30",
            week_end="2026-04-05",
            overview=_overview(close=None),
            rep_performance=[],
            top_objections=[],
        )
        assert "—" in _as_text(blocks)

    def test_rep_with_none_avg_score_excluded_from_coaching(self):
        reps = [
            _rep("HasScore", total=5, avg=5.0),
            _rep("NoScore", total=5, avg=None),
        ]
        blocks = build_weekly_report_blocks(
            week_start="2026-03-30",
            week_end="2026-04-05",
            overview=_overview(),
            rep_performance=reps,
            top_objections=[],
        )
        text = _as_text(blocks)
        # NoScore rep should still appear in top performers if close is set,
        # but must not appear in "Needs Coaching" since avg is None
        coaching_idx = text.find("Needs Coaching")
        if coaching_idx != -1:
            coaching_section = text[coaching_idx:]
            assert "NoScore" not in coaching_section

    def test_no_eligible_reps_still_renders_report(self):
        # All reps have <3 calls → no top performers / coaching sections,
        # but overview + objections should still render
        reps = [_rep("LowVol", total=1)]
        blocks = build_weekly_report_blocks(
            week_start="2026-03-30",
            week_end="2026-04-05",
            overview=_overview(),
            rep_performance=reps,
            top_objections=[],
        )
        text = _as_text(blocks)
        assert "Weekly Sales Report" in text
        assert "Top Performers" not in text
        assert "Needs Coaching" not in text


# ── Fallback text ────────────────────────────────────────────────────────────

class TestFallbackText:
    def test_empty_week(self):
        text = build_weekly_fallback_text("2026-03-30", 0, None)
        assert "no calls" in text
        assert "2026-03-30" in text

    def test_populated_week(self):
        text = build_weekly_fallback_text("2026-03-30", 150, 28.5)
        assert "150 calls" in text
        assert "28.5%" in text
