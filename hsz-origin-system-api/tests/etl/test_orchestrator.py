from datetime import datetime, timedelta

from app.etl.orchestrator import aligned_live_window, iter_windows


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
