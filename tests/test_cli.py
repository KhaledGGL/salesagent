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
