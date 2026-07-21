"""凌晨核对最近窗口，只补源端唯一交易数大于中心 ODS 数量的服务器窗口。"""

from datetime import datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.config import EtlSettings
from app.etl.formal_sync import sync_window
from app.etl.source_config import load_mapping, load_sources
from app.etl.source_lock import source_read_lock
from app.etl.source_reader import realtime_complete_windows, source_connection, window_counts
from app.etl.source_schema import monthly_table

settings = EtlSettings()


def completed_windows(now: datetime, lookback_days: int = 7):
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=lookback_days)
    current = start
    while current < end:
        yield current, current + timedelta(hours=2)
        current += timedelta(hours=2)


def latest_source_counts(
    db, start: datetime, end: datetime
) -> dict[tuple[int, datetime], tuple[str, int]]:
    """状态取最近批次，数量直接取中心 ODS，兼容旧批次的原始行数口径。"""
    rows = db.execute(
        text(
            "SELECT s.source_server_id,b.window_start,s.status "
            "FROM t_etl_batch_source s JOIN t_etl_batch b ON b.batch_id=s.batch_id "
            "WHERE b.window_start>=:start AND b.window_end<=:end "
            "ORDER BY b.batch_id DESC"
        ),
        {"start": start, "end": end},
    ).mappings()
    statuses: dict[tuple[int, datetime], str] = {}
    for row in rows:
        statuses.setdefault(
            (row["source_server_id"], row["window_start"]), row["status"]
        )

    center_counts: dict[tuple[int, datetime], int] = {}
    current = start
    while current < end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        current_end = min(next_month, end)
        table = f"t_ods_event_{current:%Y%m}"
        count_rows = db.execute(
            text(
                f"SELECT source_server_id,DATE(event_time) AS stat_date,"
                f"FLOOR(HOUR(event_time)/2) AS hour_group,COUNT(*) AS row_count "
                f"FROM `{table}` WHERE event_time>=:start AND event_time<:end "
                f"GROUP BY source_server_id,DATE(event_time),FLOOR(HOUR(event_time)/2)"
            ),
            {"start": current, "end": current_end},
        ).mappings()
        for row in count_rows:
            window_start = datetime.combine(
                row["stat_date"], datetime.min.time()
            ).replace(hour=int(row["hour_group"]) * 2)
            center_counts[(row["source_server_id"], window_start)] = int(row["row_count"])
        current = current_end

    keys = set(statuses) | set(center_counts)
    return {
        key: (statuses.get(key, "MISSING"), center_counts.get(key, 0)) for key in keys
    }


def _contiguous_ranges(windows: list[tuple[datetime, datetime]]):
    if not windows:
        return
    range_start, range_end = windows[0]
    for start, end in windows[1:]:
        if start == range_end and start.strftime("%Y%m") == range_start.strftime("%Y%m"):
            range_end = end
        else:
            yield range_start, range_end
            range_start, range_end = start, end
    yield range_start, range_end


def reconcile(
    now: datetime,
    lookback_days: int = 7,
    max_repairs: int = 24,
    execute: bool = True,
) -> list[dict]:
    windows = list(completed_windows(now, lookback_days))
    start, end = windows[0][0], windows[-1][1]
    with SessionLocal() as db:
        mapping = load_mapping(db)
        sources = [source for source in load_sources(db) if mapping.get(source.source_server_id)]
        synced = latest_source_counts(db, start, end)

    repairs = []
    with source_read_lock(
        settings.source_lock_timeout_seconds,
        enabled=settings.serialize_source_reads,
    ):
        for source in sources:
            connection = None
            try:
                connection = source_connection(source)
                physical_codes = list(mapping[source.source_server_id])
                complete_realtime = realtime_complete_windows(
                    connection,
                    source.current_table_name,
                    physical_codes,
                    start,
                    end,
                )
                source_counts: dict[datetime, int] = {}

                complete = [window for window in windows if window[0] in complete_realtime]
                for range_start, range_end in _contiguous_ranges(complete):
                    source_counts.update(
                        window_counts(
                            connection,
                            [source.current_table_name],
                            physical_codes,
                            range_start,
                            range_end,
                        )
                    )

                incomplete = [
                    window for window in windows if window[0] not in complete_realtime
                ]
                for range_start, range_end in _contiguous_ranges(incomplete):
                    history_table = monthly_table(source.monthly_table_pattern, range_start)
                    if not history_table:
                        raise RuntimeError("源库缺少窗口对应的历史月表")
                    source_counts.update(
                        window_counts(
                            connection,
                            [source.current_table_name, history_table],
                            physical_codes,
                            range_start,
                            range_end,
                        )
                    )
            finally:
                if connection:
                    connection.close()

            for window_start, window_end in windows:
                status, synced_count = synced.get(
                    (source.source_server_id, window_start), ("MISSING", 0)
                )
                source_count = source_counts.get(window_start, 0)
                if status == "FAILED" or source_count > synced_count:
                    repairs.append(
                        (
                            window_start,
                            window_end,
                            source.server_code,
                            source_count,
                            synced_count,
                            status,
                        )
                    )

    results = []
    for start, end, server_code, source_count, synced_count, status in sorted(repairs)[
        :max_repairs
    ]:
        item = {
            "window_start": start,
            "window_end": end,
            "server_code": server_code,
            "source_row_count": source_count,
            "synced_row_count": synced_count,
            "previous_status": status,
            "result": None,
        }
        if execute:
            item["result"] = sync_window(start, end, server_code)
        results.append(item)
    return results
