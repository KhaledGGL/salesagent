"""Claude scoring client — mocks the Anthropic SDK entirely.

These tests catch:
- Prompt drift (invalid JSON from Claude)
- Schema drift (missing/wrong fields)
- Markdown fence regressions (Claude ignoring 'no fences' instruction)
- The error escape hatch ({"error": ...}) path
"""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services import claude_client
from app.services.claude_client import TranscriptTooShortError, score_transcript
from schemas import ScorecardOutput


def _mock_response(text: str):
    """Build a mock Anthropic response that mimics .content[].text access."""
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(content=[block])


@pytest.fixture
def mock_anthropic(mocker, sample_scorecard_json):
    """Default: return a valid scorecard JSON string."""
    mock_client = mocker.MagicMock()
    mock_client.messages.create.return_value = _mock_response(
        json.dumps(sample_scorecard_json)
    )
    mocker.patch.object(claude_client, "_client", mock_client)
    mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)
    return mock_client


def _call(**overrides):
    """Default args for score_transcript — override only what the test cares about."""
    kwargs = dict(
        transcript="REP: Hi. PROSPECT: Hello." * 100,
        rep_name="Sarah",
        lead_name="John Smith",
        lead_source="meta",
        lead_temperature="warm",
        call_type="discovery",
        duration_seconds=1200,
    )
    kwargs.update(overrides)
    return score_transcript(**kwargs)


class TestScoreTranscript:
    def test_valid_json_returns_scorecard(self, mock_anthropic):
        result = _call()
        assert isinstance(result, ScorecardOutput)
        assert result.scores.overall == 7
        assert result.ai_summary.startswith("Solid")

    def test_markdown_fence_stripped(self, mocker, sample_scorecard_json):
        fenced = "```json\n" + json.dumps(sample_scorecard_json) + "\n```"
        mock_client = mocker.MagicMock()
        mock_client.messages.create.return_value = _mock_response(fenced)
        mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)

        result = _call()
        assert result.scores.overall == 7

    def test_plain_triple_backtick_stripped(self, mocker, sample_scorecard_json):
        fenced = "```\n" + json.dumps(sample_scorecard_json) + "\n```"
        mock_client = mocker.MagicMock()
        mock_client.messages.create.return_value = _mock_response(fenced)
        mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)

        assert _call().scores.overall == 7

    def test_transcript_too_short_raises(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            '{"error": "transcript under 5 minutes"}'
        )
        mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)

        with pytest.raises(TranscriptTooShortError, match="under 5 minutes"):
            _call()

    def test_invalid_json_raises_value_error(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.messages.create.return_value = _mock_response("not json at all {")
        mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)

        with pytest.raises(ValueError, match="not valid JSON"):
            _call()

    def test_out_of_range_score_raises_validation_error(self, mocker, sample_scorecard_json):
        # Overall score of 15 — outside 1-10. Pydantic must catch.
        sample_scorecard_json["scores"]["overall"] = 15
        mock_client = mocker.MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            json.dumps(sample_scorecard_json)
        )
        mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)

        with pytest.raises(ValidationError):
            _call()

    def test_missing_required_field_raises_validation_error(self, mocker, sample_scorecard_json):
        del sample_scorecard_json["ai_summary"]
        mock_client = mocker.MagicMock()
        mock_client.messages.create.return_value = _mock_response(
            json.dumps(sample_scorecard_json)
        )
        mocker.patch.object(claude_client, "get_anthropic", return_value=mock_client)

        with pytest.raises(ValidationError):
            _call()

    def test_duration_converted_to_minutes(self, mock_anthropic):
        _call(duration_seconds=600)
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "10.0 minutes" in user_content

    def test_uses_sonnet_model(self, mock_anthropic):
        _call()
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == 2048
