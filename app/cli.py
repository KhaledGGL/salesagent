"""Ops recovery CLI — manual replay of pipeline tasks.

Usage:
    python -m app.cli replay-notification <call_id>
    python -m app.cli replay-scoring <call_id>
    python -m app.cli run-weekly-report

Each subcommand enqueues the corresponding Celery task via the existing
broker so operators never need to SSH into a worker container to invoke
tasks directly. Enqueued jobs inherit the normal retry/backoff behavior.
"""

import argparse
import sys
from typing import Callable


def _enqueue(label: str, task_fn: Callable, *args) -> int:
    result = task_fn.delay(*args)
    print(f"Enqueued {label}({', '.join(map(str, args))}) — task id: {result.id}")
    return 0


def _cmd_replay_notification(args: argparse.Namespace) -> int:
    from app.workers.tasks import notify_scorecard
    return _enqueue("notify_scorecard", notify_scorecard, args.call_id)


def _cmd_replay_scoring(args: argparse.Namespace) -> int:
    from app.workers.tasks import score_call
    return _enqueue("score_call", score_call, args.call_id)


def _cmd_run_weekly_report(args: argparse.Namespace) -> int:
    from app.workers.tasks import generate_weekly_report
    return _enqueue("generate_weekly_report", generate_weekly_report)


def _cmd_run_coaching_lesson(args: argparse.Namespace) -> int:
    from app.workers.tasks import generate_coaching_lesson_task
    return _enqueue("generate_coaching_lesson", generate_coaching_lesson_task)


def _cmd_run_marketing_intel(args: argparse.Namespace) -> int:
    from app.workers.tasks import generate_marketing_intel_task
    return _enqueue("generate_marketing_intel", generate_marketing_intel_task)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="salesagent",
        description="Ops CLI for the Sales Call Analyzer pipeline.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_notify = sub.add_parser(
        "replay-notification",
        help="Re-post a scorecard to Slack (safe to replay — idempotent Slack posts).",
    )
    p_notify.add_argument("call_id", help="UUID of the call row to re-notify")
    p_notify.set_defaults(func=_cmd_replay_notification)

    p_score = sub.add_parser(
        "replay-scoring",
        help="Re-run Claude scoring for a call (spends Claude credits — use sparingly).",
    )
    p_score.add_argument("call_id", help="UUID of the call row to re-score")
    p_score.set_defaults(func=_cmd_replay_scoring)

    p_report = sub.add_parser(
        "run-weekly-report",
        help="Manually trigger the weekly report task (normally runs via Celery beat).",
    )
    p_report.set_defaults(func=_cmd_run_weekly_report)

    p_coaching = sub.add_parser(
        "run-coaching-lesson",
        help="Manually trigger the coaching lesson task (normally runs via Celery beat).",
    )
    p_coaching.set_defaults(func=_cmd_run_coaching_lesson)

    p_marketing = sub.add_parser(
        "run-marketing-intel",
        help="Manually trigger the marketing intelligence task (normally runs via Celery beat).",
    )
    p_marketing.set_defaults(func=_cmd_run_marketing_intel)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
