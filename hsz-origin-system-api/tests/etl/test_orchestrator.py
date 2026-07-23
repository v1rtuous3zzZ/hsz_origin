from datetime import datetime, timedelta
from unittest.mock import patch

from app.etl.orchestrator import (
    _sync_history_window_with_split,
    _sync_resumable_window,
    aligned_live_window,
    iter_windows,
    sync_range,
)
from app.etl.source_coverage import covers_window as _covers_window


def test_history_timeout_splits_window_to_smaller_queries():
    start = datetime(2026, 1, 1)
    end = start + timedelta(hours=2)
    outcomes = [
        {"status": "FAILED", "error": "TimeoutError: slow"},
        {"status": "SUCCESS"},
        {"status": "SUCCESS"},
    ]
    with patch("app.etl.orchestrator._sync_resumable_window", side_effect=outcomes) as sync:
        result = _sync_history_window_with_split(start, end, marker=True)

    assert result["status"] == "SUCCESS"
    assert sync.call_count == 3
    assert sync.call_args_list[1].args == (start, start + timedelta(hours=1))


def test_processed_count_does_not_count_failed_window_twice():
    start = datetime(2026, 1, 1)
    with (
        patch("app.etl.orchestrator._sync_history_window_with_split", return_value={"status": "FAILED"}),
        patch("app.etl.orchestrator.shanghai_now", return_value=datetime(2026, 7, 1)),
    ):
        result = sync_range(start, start + timedelta(hours=2), rebuild_facts=False)

    assert result["processed_count"] == 1
    assert result["failed_count"] == 1


def test_smaller_successful_intervals_cover_a_larger_history_window():
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 1, 6)

    assert _covers_window(
        [
            (start, start + timedelta(hours=2)),
            (start + timedelta(hours=2), start + timedelta(hours=4)),
            (start + timedelta(hours=4), end),
        ],
        start,
        end,
    )


def test_history_coverage_rejects_a_gap_between_successful_intervals():
    start = datetime(2026, 1, 1)
    end = datetime(2026, 1, 1, 6)

    assert not _covers_window(
        [
            (start, start + timedelta(hours=2)),
            (start + timedelta(hours=4), end),
        ],
        start,
        end,
    )


def test_live_window_is_aligned_and_respects_safety_delay():
    start, end = aligned_live_window(
        datetime(2026, 7, 21, 10, 1),
        window_minutes=120,
        safety_delay=timedelta(minutes=2),
    )
    assert start == datetime(2026, 7, 21, 6)
    assert end == datetime(2026, 7, 21, 8)


def test_live_window_at_fifteen_minutes_uses_just_completed_window():
    start, end = aligned_live_window(
        datetime(2026, 7, 21, 10, 15),
        window_minutes=120,
        safety_delay=timedelta(minutes=2),
    )
    assert start == datetime(2026, 7, 21, 8)
    assert end == datetime(2026, 7, 21, 10)


def test_history_windows_never_cross_month():
    windows = list(
        iter_windows(
            datetime(2026, 1, 31, 23),
            datetime(2026, 2, 1, 3),
            minutes=120,
        )
    )
    assert windows == [
        (datetime(2026, 1, 31, 23), datetime(2026, 2, 1)),
        (datetime(2026, 2, 1), datetime(2026, 2, 1, 2)),
        (datetime(2026, 2, 1, 2), datetime(2026, 2, 1, 3)),
    ]


def test_resume_skips_an_already_successful_explicit_server():
    start, end = datetime(2026, 7, 21, 8), datetime(2026, 7, 21, 10)
    with (
        patch("app.etl.orchestrator.window_was_successful", return_value=True),
        patch("app.etl.orchestrator.sync_window") as sync,
    ):
        result = _sync_resumable_window(
            start,
            end,
            server_code="source-a",
            resume=True,
            rebuild_facts=False,
            job_code="HISTORY_SYNC",
            job_type="BACKFILL",
            default_source_mode="HISTORY",
            source_batch_size=2000,
            max_workers=4,
        )

    assert result["status"] == "SKIPPED"
    sync.assert_not_called()


def test_resume_reads_only_missing_servers_for_a_partial_window():
    start, end = datetime(2026, 7, 21, 8), datetime(2026, 7, 21, 10)
    with (
        patch("app.etl.orchestrator.expected_server_codes", return_value={"a", "b"}),
        patch("app.etl.orchestrator.missing_server_codes", return_value=["b"]),
        patch(
            "app.etl.orchestrator.sync_window", return_value={"status": "SUCCESS"}
        ) as sync,
    ):
        result = _sync_resumable_window(
            start,
            end,
            server_code=None,
            resume=True,
            rebuild_facts=False,
            job_code="HISTORY_SYNC",
            job_type="BACKFILL",
            default_source_mode="HISTORY",
            source_batch_size=2000,
            max_workers=4,
        )

    assert result["status"] == "SUCCESS"
    assert result["repaired_servers"] == ["b"]
    sync.assert_called_once_with(
        start,
        end,
        "b",
        rebuild_facts=False,
        job_code="HISTORY_SYNC",
        job_type="BACKFILL",
        default_source_mode="HISTORY",
        source_batch_size=2000,
        max_workers=1,
        skip_successful_sources=True,
    )
