"""Slack Block Kit helpers for keeping long content under Slack's limits.

Slack rejects any section `text.text` longer than 3000 characters with
`invalid_blocks`. The weekly reports build sections by concatenating
per-entry lines (objections, gaps, reps, etc.) and Claude-verbose weeks
have pushed individual sections past that limit — failing the whole
message.

Callers build content as a list of pre-formatted lines and pass them
through `chunk_mrkdwn_section`, which emits one or more section blocks,
each guaranteed under the safe limit.
"""

from typing import Any

# Slack's hard limit is 3000; leave a buffer for JSON overhead / emoji bytes.
SAFE_SECTION_TEXT_LIMIT = 2900


def chunk_mrkdwn_section(
    header: str,
    lines: list[str],
    *,
    limit: int = SAFE_SECTION_TEXT_LIMIT,
) -> list[dict[str, Any]]:
    """Build one or more mrkdwn `section` blocks, each under `limit` chars.

    The header renders once at the top of the first emitted block. Lines
    are joined with `\\n` and split across additional blocks when
    appending the next line would exceed the limit. A single line longer
    than the limit is truncated with an ellipsis so Slack still accepts
    the block.

    Returns `[]` when `lines` is empty so callers don't emit a header-only
    section.
    """
    if not lines:
        return []

    if len(header) > limit:
        header = header[: limit - 1] + "…"

    safe_lines: list[str] = []
    for line in lines:
        if len(line) > limit:
            safe_lines.append(line[: limit - 1] + "…")
        else:
            safe_lines.append(line)

    blocks: list[dict[str, Any]] = []
    current = header
    for line in safe_lines:
        candidate = (current + "\n" + line) if current else line
        if len(candidate) > limit:
            if current:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": current}})
            current = line
        else:
            current = candidate
    if current:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": current}})
    return blocks
