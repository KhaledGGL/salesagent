"""Slack client — thin wrapper around slack_sdk WebClient.

Single shared client instance (slack_sdk is thread-safe).
Uses chat.postMessage for main + threaded coaching replies.
"""

import logging
from typing import Any

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from core.config import settings

logger = logging.getLogger(__name__)

_client: WebClient | None = None


def get_slack() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=settings.slack_bot_token)
    return _client


def post_message(
    channel: str,
    blocks: list[dict[str, Any]],
    text: str,
    thread_ts: str | None = None,
) -> str:
    """Post a message. Returns the ts (message id) for threading.

    Args:
        channel: channel name or id (e.g. "sales-scorecards" or "C012345")
        blocks: Block Kit blocks
        text: fallback plaintext for notifications / screen readers
        thread_ts: if provided, post as a reply in that thread

    Raises:
        SlackApiError: propagates so Celery can retry with backoff.
    """
    try:
        resp = get_slack().chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=text,
            thread_ts=thread_ts,
            unfurl_links=False,
            unfurl_media=False,
        )
        return resp["ts"]
    except SlackApiError as exc:
        logger.error("Slack post failed: channel=%s error=%s", channel, exc.response.get("error"))
        raise
