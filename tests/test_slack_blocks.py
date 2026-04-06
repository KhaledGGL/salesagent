"""Block Kit output regression guards.

These assertions are intentionally loose — we check presence of key
signals (emoji, banner, button) rather than exact JSON equality,
so cosmetic tweaks don't break tests.
"""

import json

from app.core.slack_blocks import (
    _fmt_seconds,
    _outcome_emoji,
    _score_emoji,
    _severity_emoji,
    build_coaching_moment_block,
    build_fallback_text,
    build_objections_summary_block,
    build_scorecard_blocks,
)


SCORES = {
    "rapport": 7,
    "diagnosis": 8,
    "objection_handling": 6,
    "close": 7,
    "compliance": 9,
}


def _as_text(blocks) -> str:
    """Flatten blocks to a searchable string for assertion.

    ensure_ascii=False preserves emoji so assertions can match literal
    characters rather than \\uXXXX escapes.
    """
    return json.dumps(blocks, ensure_ascii=False)


# ── Emoji helpers ────────────────────────────────────────────────────────────

class TestScoreEmoji:
    def test_green_for_high(self):
        assert _score_emoji(10) == "🟢"
        assert _score_emoji(8) == "🟢"

    def test_yellow_for_mid(self):
        assert _score_emoji(7) == "🟡"
        assert _score_emoji(5) == "🟡"

    def test_red_for_low(self):
        assert _score_emoji(4) == "🔴"
        assert _score_emoji(1) == "🔴"


class TestFmtSeconds:
    def test_under_minute(self):
        assert _fmt_seconds(45) == "0:45"

    def test_minute_and_seconds(self):
        assert _fmt_seconds(125) == "2:05"

    def test_zero(self):
        assert _fmt_seconds(0) == "0:00"

    def test_exact_minute(self):
        assert _fmt_seconds(600) == "10:00"


class TestSeverityEmoji:
    def test_high(self):
        assert _severity_emoji("high") == "🚨"

    def test_unknown(self):
        assert _severity_emoji("nonsense") == "•"


class TestOutcomeEmoji:
    def test_sold(self):
        assert _outcome_emoji("sold") == "✅"

    def test_no_show(self):
        assert _outcome_emoji("no_show") == "👻"

    def test_none(self):
        assert _outcome_emoji(None) == "•"


# ── Main scorecard blocks ────────────────────────────────────────────────────

def _build(overall=7, therapist=False, reason=None, win_loss=True, recording=True):
    return build_scorecard_blocks(
        rep_name="Sarah",
        lead_name="John Smith",
        lead_source="meta",
        outcome="sold",
        scores=SCORES,
        overall_score=overall,
        therapist_mode_flag=therapist,
        therapist_mode_reason=reason,
        ai_summary="Solid discovery, weak close.",
        win_loss_timestamp=645 if win_loss else None,
        win_loss_description="Breakthrough moment on budget." if win_loss else None,
        recording_url="https://example.com/rec.mp3" if recording else None,
    )


class TestBuildScorecardBlocks:
    def test_green_score_renders_green_emoji(self):
        text = _as_text(_build(overall=9))
        assert "🟢 Sarah — 9/10" in text

    def test_yellow_score_renders_yellow_emoji(self):
        text = _as_text(_build(overall=6))
        assert "🟡 Sarah — 6/10" in text

    def test_red_score_renders_red_emoji(self):
        text = _as_text(_build(overall=3))
        assert "🔴 Sarah — 3/10" in text

    def test_therapist_banner_present_when_flagged(self):
        text = _as_text(_build(therapist=True, reason="Rep talked 70% of the time."))
        assert "Therapist Mode Triggered" in text
        assert "Rep talked 70%" in text

    def test_therapist_banner_absent_when_not_flagged(self):
        text = _as_text(_build(therapist=False))
        assert "Therapist Mode Triggered" not in text

    def test_recording_button_present(self):
        text = _as_text(_build(recording=True))
        assert "Listen to recording" in text
        assert "example.com/rec.mp3" in text

    def test_recording_button_absent_when_no_url(self):
        text = _as_text(_build(recording=False))
        assert "Listen to recording" not in text

    def test_win_loss_moment_rendered(self):
        text = _as_text(_build(win_loss=True))
        assert "Key Moment" in text
        assert "Breakthrough moment" in text
        assert "10:45" in text  # 645 seconds → 10:45

    def test_win_loss_absent_when_none(self):
        text = _as_text(_build(win_loss=False))
        assert "Key Moment" not in text

    def test_all_five_score_fields_present(self):
        blocks = _build()
        section = next(b for b in blocks if b.get("type") == "section" and "fields" in b)
        labels = [f["text"] for f in section["fields"]]
        assert any("Rapport" in l for l in labels)
        assert any("Diagnosis" in l for l in labels)
        assert any("Objection" in l for l in labels)
        assert any("Close" in l for l in labels)
        assert any("Compliance" in l for l in labels)

    def test_ai_summary_present(self):
        text = _as_text(_build())
        assert "Solid discovery" in text


class TestCoachingMomentBlock:
    def test_high_severity_renders_alarm(self):
        blocks = build_coaching_moment_block(
            timestamp_seconds=300,
            category="diagnosis",
            severity="high",
            note="Skipped consequence questions.",
        )
        text = _as_text(blocks)
        assert "🚨" in text
        assert "Diagnosis" in text
        assert "5:00" in text
        assert "Skipped consequence" in text

    def test_category_humanized(self):
        blocks = build_coaching_moment_block(
            timestamp_seconds=0,
            category="objection_handling",
            severity="low",
            note="note",
        )
        assert "Objection Handling" in _as_text(blocks)


class TestObjectionsSummary:
    def test_empty_returns_empty_list(self):
        assert build_objections_summary_block([]) == []

    def test_renders_all_objections(self):
        blocks = build_objections_summary_block([
            {
                "timestamp_seconds": 120,
                "objection_type": "price",
                "objection_text": "Too expensive",
                "handling_quality": "good",
            },
            {
                "timestamp_seconds": 480,
                "objection_type": "spouse",
                "objection_text": "Need to talk to wife",
                "handling_quality": "fair",
            },
        ])
        text = _as_text(blocks)
        assert "price" in text
        assert "spouse" in text
        assert "Too expensive" in text
        assert "2:00" in text
        assert "8:00" in text


class TestFallbackText:
    def test_contains_rep_and_score(self):
        text = build_fallback_text("Sarah", 8, "sold")
        assert "Sarah" in text
        assert "8/10" in text
        assert "sold" in text

    def test_handles_none_outcome(self):
        text = build_fallback_text("Sarah", 5, None)
        assert "outcome unknown" in text
