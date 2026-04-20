"""Marketing intelligence Block Kit regression tests."""

import json

from app.core.marketing_blocks import (
    build_marketing_fallback_text,
    build_marketing_intel_blocks,
)
from schemas import (
    MarketingIntelOutput,
    MessagingAngle,
    PositioningGap,
    PrequalRec,
    SourceAnalysis,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _as_text(blocks) -> str:
    return json.dumps(blocks, ensure_ascii=False)


def _intel(
    headline="Price objections dominate",
    angles=None,
    sources=None,
    prequal=None,
    gaps=None,
):
    return MarketingIntelOutput(
        headline=headline,
        messaging_angles=angles or [],
        source_analysis=sources or [],
        prequalification_recs=prequal or [],
        positioning_gaps=gaps or [],
    )


# ── Header tests ────────────────────────────────────────────────────────────

class TestHeader:
    def test_header_contains_dates(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12", intel=_intel(),
        )
        text = _as_text(blocks)
        assert "2026-04-06" in text
        assert "2026-04-12" in text

    def test_header_has_emoji(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12", intel=_intel(),
        )
        assert blocks[0]["type"] == "header"
        assert "📈" in blocks[0]["text"]["text"]

    def test_headline_rendered(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(headline="Meta leads underperforming"),
        )
        text = _as_text(blocks)
        assert "Meta leads underperforming" in text


# ── Messaging angles tests ──────────────────────────────────────────────────

class TestMessagingAngles:
    def test_angles_rendered(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(angles=[
                MessagingAngle(
                    pain_point="Lead quality",
                    frequency=8,
                    example_quotes=["Our leads never convert"],
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "Lead quality" in text
        assert "8x" in text
        assert "Our leads never convert" in text
        assert "Messaging Angles" in text

    def test_no_angles_section_when_empty(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(angles=[]),
        )
        text = _as_text(blocks)
        assert "Messaging Angles" not in text

    def test_multiple_quotes_truncated_to_two(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(angles=[
                MessagingAngle(
                    pain_point="Cost",
                    frequency=5,
                    example_quotes=["Quote1", "Quote2", "Quote3"],
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "Quote1" in text
        assert "Quote2" in text
        assert "Quote3" not in text


# ── Source analysis tests ───────────────────────────────────────────────────

class TestSourceAnalysis:
    def test_source_rendered(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(sources=[
                SourceAnalysis(
                    source="meta",
                    close_rate=25.0,
                    quality_assessment="High volume, low quality",
                    recommendation="Tighten targeting",
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "meta" in text
        assert "25.0%" in text
        assert "High volume, low quality" in text
        assert "Tighten targeting" in text

    def test_null_close_rate_shows_dash(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(sources=[
                SourceAnalysis(
                    source="organic",
                    close_rate=None,
                    quality_assessment="Unknown",
                    recommendation="Track better",
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "—" in text

    def test_no_source_section_when_empty(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(sources=[]),
        )
        text = _as_text(blocks)
        assert "Lead Source Quality" not in text


# ── Pre-qualification recs tests ────────────────────────────────────────────

class TestPrequalRecs:
    def test_prequal_rendered(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(prequal=[
                PrequalRec(
                    recommendation="Require budget confirmation",
                    rationale="60% of lost calls cite price as blocker",
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "Require budget confirmation" in text
        assert "60% of lost calls" in text
        assert "Pre-Qualification" in text

    def test_numbered_list(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(prequal=[
                PrequalRec(recommendation="First", rationale="Because A"),
                PrequalRec(recommendation="Second", rationale="Because B"),
            ]),
        )
        text = _as_text(blocks)
        assert "1." in text
        assert "2." in text

    def test_no_prequal_section_when_empty(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(prequal=[]),
        )
        text = _as_text(blocks)
        assert "Pre-Qualification" not in text


# ── Positioning gaps tests ──────────────────────────────────────────────────

class TestPositioningGaps:
    def test_gap_rendered(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(gaps=[
                PositioningGap(
                    gap="ROI timeline mismatch",
                    evidence="Ads say 7 days, reps say 30",
                    recommendation="Align ad copy to 30-day timeline",
                ),
            ]),
        )
        text = _as_text(blocks)
        assert "ROI timeline mismatch" in text
        assert "Ads say 7 days" in text
        assert "Align ad copy" in text

    def test_no_gap_section_when_empty(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(gaps=[]),
        )
        text = _as_text(blocks)
        assert "Positioning Gaps" not in text


# ── Full report test ────────────────────────────────────────────────────────

class TestFullReport:
    def test_all_sections_present(self):
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(
                angles=[MessagingAngle(pain_point="X", frequency=1, example_quotes=["q"])],
                sources=[SourceAnalysis(source="meta", close_rate=20.0, quality_assessment="ok", recommendation="keep")],
                prequal=[PrequalRec(recommendation="R", rationale="why")],
                gaps=[PositioningGap(gap="G", evidence="E", recommendation="F")],
            ),
        )
        text = _as_text(blocks)
        assert "Messaging Angles" in text
        assert "Lead Source Quality" in text
        assert "Pre-Qualification" in text
        assert "Positioning Gaps" in text


# ── Fallback text tests ────────────────────────────────────────────────────

class TestFallbackText:
    def test_zero_calls(self):
        assert "no calls" in build_marketing_fallback_text("2026-04-06", 0)

    def test_with_calls(self):
        text = build_marketing_fallback_text("2026-04-06", 42)
        assert "42" in text
        assert "2026-04-06" in text


# ── Section chunking regression ─────────────────────────────────────────────

class TestSectionChunking:
    """Slack rejects a section whose text exceeds 3000 chars with
    `invalid_blocks`. When Claude is verbose, a single category's entries
    can blow past that. Every section block we emit must stay under the
    limit; the render still includes every entry.
    """

    def test_long_positioning_gaps_split_across_blocks(self):
        long_evidence = "x" * 500
        gaps = [
            PositioningGap(
                gap=f"Gap {i}",
                evidence=long_evidence,
                recommendation=f"Fix {i}",
            )
            for i in range(10)
        ]
        blocks = build_marketing_intel_blocks(
            week_start="2026-04-06", week_end="2026-04-12",
            intel=_intel(gaps=gaps),
        )
        section_lengths = [
            len(b["text"]["text"])
            for b in blocks
            if b.get("type") == "section" and b["text"].get("type") == "mrkdwn"
        ]
        assert section_lengths, "expected at least one mrkdwn section"
        assert all(length < 3000 for length in section_lengths), (
            f"section text lengths must stay under Slack's 3000-char limit: {section_lengths}"
        )

        text = _as_text(blocks)
        for i in range(10):
            assert f"Gap {i}" in text
            assert f"Fix {i}" in text
