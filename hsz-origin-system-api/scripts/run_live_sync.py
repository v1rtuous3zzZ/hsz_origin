"""Run the last complete two-hour ETL window in Asia/Shanghai."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.etl.formal_sync import sync_window


def windows(start: datetime, end: datetime):
    current = start
    while current < end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        current_end = min(end, next_month)
        yield current, current_end
        current = current_end


def main() -> None:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=2)
    for window_start, window_end in windows(start, end):
        sync_window(window_start, window_end)


if __name__ == "__main__":
    main()
