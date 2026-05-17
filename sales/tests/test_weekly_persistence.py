"""Tests for _persist_weekly_report — the helper that upserts each
weekly Claude-generated report to the weekly_reports table so the UI
can read them historically without re-running Claude."""

import pytest


@pytest.fixture
def fake_db(mocker):
    """Patch app.workers.tasks.get_supabase to a MagicMock and return it."""
    db = mocker.MagicMock()
    mocker.patch("sales.app.workers.tasks.get_supabase", return_value=db)
    return db


def _upsert_call_args(fake_db):
    """Pull out the dict that was passed to .table('weekly_reports').upsert(...)."""
    return fake_db.table.return_value.upsert.call_args


class TestPersistWeeklyReport:
    def test_empty_week_start_is_no_op(self, fake_db):
        from sales.app.workers.tasks import _persist_weekly_report

        _persist_weekly_report("sales", "", "", {"any": "data"})

        # Should never have touched the DB
        fake_db.table.assert_not_called()

    def test_none_week_start_is_no_op(self, fake_db):
        from sales.app.workers.tasks import _persist_weekly_report

        _persist_weekly_report("sales", None, None, {"any": "data"})

        fake_db.table.assert_not_called()

    def test_upsert_payload_shape(self, fake_db):
        from sales.app.workers.tasks import _persist_weekly_report

        _persist_weekly_report(
            "coaching",
            "2026-04-27",
            "2026-05-03",
            {"headline": "test", "weekly_focus": "consequence questions"},
        )

        fake_db.table.assert_called_once_with("weekly_reports")
        args, kwargs = _upsert_call_args(fake_db)
        row = args[0]
        assert row["report_type"] == "coaching"
        assert row["week_start"] == "2026-04-27"
        assert row["week_end"] == "2026-05-03"
        assert row["payload"]["headline"] == "test"

    def test_upsert_uses_on_conflict_for_idempotency(self, fake_db):
        from sales.app.workers.tasks import _persist_weekly_report

        _persist_weekly_report("marketing", "2026-04-27", "2026-05-03", {"x": 1})

        _, kwargs = _upsert_call_args(fake_db)
        # Critical for retry safety: same week + same type = update, not duplicate
        assert kwargs.get("on_conflict") == "report_type,week_start"

    def test_week_end_falls_back_to_week_start_if_missing(self, fake_db):
        """A degenerate but observed shape: week_start present, week_end empty."""
        from sales.app.workers.tasks import _persist_weekly_report

        _persist_weekly_report("sales", "2026-04-27", "", {"data": True})

        args, _ = _upsert_call_args(fake_db)
        assert args[0]["week_end"] == "2026-04-27"

    def test_db_failure_is_logged_not_raised(self, fake_db, caplog):
        """Slack delivery is the user-facing deliverable. Persistence is
        best-effort — a DB error must NOT propagate up to the task and
        trigger a retry that re-runs Claude."""
        from sales.app.workers.tasks import _persist_weekly_report

        fake_db.table.return_value.upsert.return_value.execute.side_effect = (
            RuntimeError("supabase exploded")
        )

        # Must not raise
        _persist_weekly_report("sales", "2026-04-27", "2026-05-03", {"x": 1})

        # But the failure should be visible in logs
        assert any("weekly_reports upsert failed" in rec.message for rec in caplog.records)

    def test_report_type_values_match_sql_enum(self):
        """The three string values must match the SQL enum exactly. If we
        ever rename one in the migration, this catches the drift."""
        from sales.schemas import WeeklyReportType

        assert {t.value for t in WeeklyReportType} == {"sales", "coaching", "marketing"}
