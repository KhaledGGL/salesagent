"""Replay CLI tests — argument parsing + task enqueue behavior.

Mocks the Celery .delay() calls so nothing touches a real broker.
"""

import pytest

from app.cli import build_parser, main


class TestArgumentParsing:
    def test_replay_notification_requires_call_id(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["replay-notification"])

    def test_replay_scoring_requires_call_id(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["replay-scoring"])

    def test_run_weekly_report_no_args(self):
        parser = build_parser()
        args = parser.parse_args(["run-weekly-report"])
        assert args.cmd == "run-weekly-report"

    def test_unknown_command_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["nonsense"])

    def test_no_command_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestDispatch:
    def test_replay_notification_enqueues_task(self, mocker, capsys):
        mock_task = mocker.MagicMock()
        mock_task.delay.return_value = mocker.MagicMock(id="task-123")
        mocker.patch("app.workers.tasks.notify_scorecard", mock_task)

        exit_code = main(["replay-notification", "call-abc"])

        assert exit_code == 0
        mock_task.delay.assert_called_once_with("call-abc")
        assert "task-123" in capsys.readouterr().out

    def test_replay_scoring_enqueues_task(self, mocker, capsys):
        mock_task = mocker.MagicMock()
        mock_task.delay.return_value = mocker.MagicMock(id="score-456")
        mocker.patch("app.workers.tasks.score_call", mock_task)

        exit_code = main(["replay-scoring", "call-xyz"])

        assert exit_code == 0
        mock_task.delay.assert_called_once_with("call-xyz")

    def test_run_weekly_report_enqueues_task(self, mocker, capsys):
        mock_task = mocker.MagicMock()
        mock_task.delay.return_value = mocker.MagicMock(id="wr-789")
        mocker.patch("app.workers.tasks.generate_weekly_report", mock_task)

        exit_code = main(["run-weekly-report"])

        assert exit_code == 0
        mock_task.delay.assert_called_once_with()
        assert "wr-789" in capsys.readouterr().out


def _mock_failed_calls_query(mocker, rows: list[dict]):
    """Wire app.db.get_supabase so the failed-calls fetch returns `rows`."""
    fake_db = mocker.MagicMock()
    chain = (
        fake_db.table.return_value
        .select.return_value
        .eq.return_value
        .gte.return_value
        .order.return_value
        .execute
    )
    chain.return_value = mocker.MagicMock(data=rows)
    mocker.patch("app.db.get_supabase", return_value=fake_db)
    return fake_db


class TestReplayFailed:
    def test_no_failed_calls_returns_zero(self, mocker, capsys):
        _mock_failed_calls_query(mocker, [])
        exit_code = main(["replay-failed", "--days", "7"])
        assert exit_code == 0
        assert "No replayable failed calls" in capsys.readouterr().out

    def test_dry_run_does_not_enqueue(self, mocker, capsys):
        _mock_failed_calls_query(mocker, [
            {"id": "c1", "called_at": "2026-04-30T12:00:00Z", "transcript": "Rep: hi..." * 10},
            {"id": "c2", "called_at": "2026-05-01T15:00:00Z", "transcript": "Rep: hello..." * 10},
        ])
        mock_task = mocker.MagicMock()
        mocker.patch("app.workers.tasks.score_call", mock_task)

        exit_code = main(["replay-failed", "--days", "7", "--dry-run"])

        assert exit_code == 0
        mock_task.delay.assert_not_called()
        out = capsys.readouterr().out
        assert "would replay c1" in out
        assert "would replay c2" in out

    def test_skips_calls_without_transcript(self, mocker, capsys):
        _mock_failed_calls_query(mocker, [
            {"id": "c1", "called_at": "2026-04-30T12:00:00Z", "transcript": None},
            {"id": "c2", "called_at": "2026-05-01T15:00:00Z", "transcript": "Rep: hello..." * 10},
        ])
        mock_task = mocker.MagicMock()
        mock_task.delay.return_value = mocker.MagicMock(id="t-1")
        mocker.patch("app.workers.tasks.score_call", mock_task)

        exit_code = main(["replay-failed", "--days", "7"])

        assert exit_code == 0
        mock_task.delay.assert_called_once_with("c2")

    def test_enqueues_each_replayable_call(self, mocker, capsys):
        _mock_failed_calls_query(mocker, [
            {"id": "c1", "called_at": "2026-04-30T12:00:00Z", "transcript": "x" * 100},
            {"id": "c2", "called_at": "2026-05-01T15:00:00Z", "transcript": "y" * 100},
        ])
        mock_task = mocker.MagicMock()
        mock_task.delay.side_effect = [
            mocker.MagicMock(id="t-1"),
            mocker.MagicMock(id="t-2"),
        ]
        mocker.patch("app.workers.tasks.score_call", mock_task)

        exit_code = main(["replay-failed"])

        assert exit_code == 0
        assert mock_task.delay.call_count == 2
        out = capsys.readouterr().out
        assert "t-1" in out and "t-2" in out
