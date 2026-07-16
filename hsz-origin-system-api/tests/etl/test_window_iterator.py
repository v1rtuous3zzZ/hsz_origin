from datetime import datetime

from app.etl.runner import windows


def test_windows_split_and_cover_range():
    values = list(windows(datetime(2026, 6, 30, 23, 30), datetime(2026, 7, 1, 1), 60))
    assert values == [
        (datetime(2026, 6, 30, 23, 30), datetime(2026, 7, 1, 0, 30)),
        (datetime(2026, 7, 1, 0, 30), datetime(2026, 7, 1, 1)),
    ]
