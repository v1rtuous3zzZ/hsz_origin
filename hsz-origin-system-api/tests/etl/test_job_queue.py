from datetime import datetime
from unittest.mock import patch

from app.etl.job_queue import ManualSyncJob, execute_job


def make_job() -> ManualSyncJob:
    return ManualSyncJob(
        job_id=1,
        job_no="MANUAL-test",
        window_start=datetime(2026, 7, 1),
        window_end=datetime(2026, 7, 1, 4),
        window_minutes=120,
        sleep_seconds=0,
        resume=True,
        continue_on_error=True,
        rebuild_facts=False,
        server_code=None,
    )


def test_execute_job_updates_progress_and_finishes_successfully() -> None:
    def run(*args, **kwargs):
        kwargs["progress_callback"]({"processed_count": 1})
        return {"status": "SUCCESS", "window_count": 2}

    with (
        patch("app.etl.job_queue.sync_range", side_effect=run),
        patch("app.etl.job_queue.update_job_progress") as progress,
        patch("app.etl.job_queue.finish_job") as finish,
    ):
        result = execute_job(make_job())

    assert result["status"] == "SUCCESS"
    progress.assert_called_once_with(1, {"processed_count": 1})
    finish.assert_called_once_with(
        1,
        "SUCCESS",
        {"status": "SUCCESS", "window_count": 2},
    )


def test_execute_job_records_failure_without_retrying_in_http() -> None:
    with (
        patch("app.etl.job_queue.sync_range", side_effect=RuntimeError("boom")),
        patch("app.etl.job_queue.finish_job") as finish,
    ):
        result = execute_job(make_job())

    assert result["status"] == "FAILED"
    finish.assert_called_once_with(1, "FAILED", None, "boom")
