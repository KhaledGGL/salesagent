"""Coaching lesson Block Kit regression tests."""

import json

from app.core.coaching_blocks import (
    CATEGORY_EMOJI,
    CATEGORY_LABEL,
    build_coaching_fallback_text,
    build_coaching_lesson_blocks,
)
from schemas import CategoryInsight, CoachingExample, CoachingLessonOutput


# ── Helpers ──────────────────────────────────────────────────────────────────

def _as_text(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)


def _example(rep="Sarah", did="Great question", quote="Tell me more"):
    return CoachingExample(rep_name=rep, what_they_did=did, quote=quote)


def _insight(category="diagnosis", best=None, worst=None, advice="Work on this."):
    return CategoryInsight(
        category=category,
        best_examples=best or [],
        worst_examples=worst or [],
        advice=advice,
    )


def _lesson(headline="Strong week", insights=None, focus="Keep diagnosing"):
    return CoachingLessonOutput(
        headline=headline,
        category_insights=insights or [],
        weekly_focus=focus,
    )


# ── Header tests ────────────────────────────────────────────────────────────

class TestHeader:
    def test_header_contains_dates(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12", lesson=_lesson(),
        )
        text = _as_text(blocks)
        assert "2026-04-06" in text
        assert "2026-04-12" in text

    def test_header_has_emoji(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12", lesson=_lesson(),
        )
        assert blocks[0]["type"] == "header"
        assert "📚" in blocks[0]["text"]["text"]

    def test_headline_rendered(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(headline="Objection handling improved"),
        )
        text = _as_text(blocks)
        assert "Objection handling improved" in text


# ── Category insight tests ──────────────────────────────────────────────────

class TestCategoryInsights:
    def test_best_examples_rendered(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[
                _insight(
                    category="rapport",
                    best=[_example(rep="Alice", did="Built trust", quote="I hear you")],
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "Alice" in text
        assert "Built trust" in text
        assert "I hear you" in text
        assert "What went well" in text

    def test_worst_examples_rendered(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[
                _insight(
                    category="close",
                    worst=[_example(rep="Bob", did="Closed too early", quote="So ready to start?")],
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "Bob" in text
        assert "Closed too early" in text
        assert "What needs work" in text

    def test_advice_rendered(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[
                _insight(category="diagnosis", advice="Ask deeper consequence questions."),
            ]),
        )
        text = _as_text(blocks)
        assert "Ask deeper consequence questions" in text

    def test_category_emoji_used(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[_insight(category="diagnosis")]),
        )
        text = _as_text(blocks)
        assert CATEGORY_EMOJI["diagnosis"] in text

    def test_category_label_used(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[_insight(category="objection_handling")]),
        )
        text = _as_text(blocks)
        assert CATEGORY_LABEL["objection_handling"] in text

    def test_no_best_section_when_empty(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[
                _insight(category="rapport", best=[], worst=[_example()]),
            ]),
        )
        text = _as_text(blocks)
        assert "What went well" not in text
        assert "What needs work" in text

    def test_no_worst_section_when_empty(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[
                _insight(category="rapport", best=[_example()], worst=[]),
            ]),
        )
        text = _as_text(blocks)
        assert "What went well" in text
        assert "What needs work" not in text

    def test_multiple_categories(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[
                _insight(category="rapport", best=[_example(rep="A")]),
                _insight(category="close", worst=[_example(rep="B")]),
            ]),
        )
        text = _as_text(blocks)
        assert CATEGORY_LABEL["rapport"] in text
        assert CATEGORY_LABEL["close"] in text


# ── Weekly focus tests ──────────────────────────────────────────────────────

class TestWeeklyFocus:
    def test_focus_rendered(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(focus="Practice consequence questions"),
        )
        text = _as_text(blocks)
        assert "Practice consequence questions" in text
        assert "This Week's Focus" in text

    def test_focus_is_last_section(self):
        blocks = build_coaching_lesson_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            lesson=_lesson(insights=[_insight()], focus="Focus here"),
        )
        last_block = blocks[-1]
        assert last_block["type"] == "section"
        assert "Focus here" in last_block["text"]["text"]


# ── Fallback text tests ────────────────────────────────────────────────────

class TestFallbackText:
    def test_zero_calls(self):
        assert "no calls" in build_coaching_fallback_text("2026-04-06", 0)

    def test_with_calls(self):
        text = build_coaching_fallback_text("2026-04-06", 42)
        assert "42" in text
        assert "2026-04-06" in text
