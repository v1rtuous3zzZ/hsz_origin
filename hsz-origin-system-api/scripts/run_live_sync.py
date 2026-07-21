"""Run the last complete two-hour ETL window in Asia/Shanghai.

Production capacity and index notes (verified 2026-07-21):

- Across 541 successful two-hour windows, all eight reachable source servers
  produced 1,472 to 175,393 source rows per window (57,891 average). Successful
  events ranged up to 108,355 per window (36,171 average). These are observed
  values, not hard limits; batching must continue to support larger windows.
- Every collected ``dfs_gantry_transaction`` table has ``PRIMARY (TradeId)``
  and the range indexes ``(GantryId, TransTime, DealStatus)`` and
  ``(GantryId, TransTime, MUploadFlag, UploadFlag, DealStatus)``. Source reads
  must keep both ``GantryId`` and the bounded ``TransTime`` range in the WHERE
  clause. Production EXPLAIN uses ``type=range``; do not wrap these columns in
  functions or issue an unrestricted time scan.
- Monthly source tables follow the same access contract and are read only for
  physical gantries whose realtime coverage is incomplete.
- Center ODS uses ``UNIQUE (event_key)``, plus
  ``(event_time, source_server_id)``, ``(source_server_id, source_trade_id)``
  and ``(batch_id)`` indexes. Match tables use
  ``UNIQUE (event_key, object_no)`` plus ``(object_no, event_time)``,
  ``(rule_no, event_time)``, ``(source_server_id, event_time)`` and
  ``(batch_id)`` indexes.
- Center flow facts use ``PRIMARY (object_no, stat_hour/stat_date/stat_month)``
  and reverse lookup indexes ``(stat_hour/stat_date/stat_month, object_no)``.
  Monthly facts are aggregated from daily facts, not by rescanning a full
  month of match details for every two-hour run.

The source connection is closed after detail extraction. Normalization,
matching, batched inserts and fact rebuilding run only against the center DB.
"""

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
