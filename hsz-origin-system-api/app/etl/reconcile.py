"""凌晨核对最近窗口，只补源端行数大于中心入库行数的服务器窗口。"""

from datetime import datetime, timedelta

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.formal_sync import sync_window
from app.etl.source_config import load_mapping, load_sources
from app.etl.source_reader import realtime_complete_windows, source_connection, window_counts
from app.etl.source_schema import monthly_table


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
    rows = db.execute(
        text(
            "SELECT s.source_server_id,b.window_start,s.status,s.source_row_count "
            "FROM t_etl_batch_source s JOIN t_etl_batch b ON b.batch_id=s.batch_id "
            "WHERE b.window_start>=:start AND b.window_end<=:end "
            "ORDER BY b.batch_id DESC"
        ),
        {"start": start, "end": end},
    ).mappings()
    result: dict[tuple[int, datetime], tuple[str, int]] = {}
    for row in rows:
        result.setdefault(
            (row["source_server_id"], row["window_start"]),
            (row["status"], row["source_row_count"]),
        )
    return result


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
    for source in sources:
        connection = None
        try:
            connection = source_connection(source)
            source_counts = {}
            grouped_windows = {}
            complete_realtime = realtime_complete_windows(
                connection,
                source.current_table_name,
                list(mapping[source.source_server_id]),
                start,
                end,
            )
            for window_start, window_end in windows:
                tables = [source.current_table_name]
                if window_start not in complete_realtime:
                    history_table = monthly_table(source.monthly_table_pattern, window_start)
                    if not history_table:
                        raise RuntimeError("源库缺少窗口对应的历史月表")
                    tables.append(history_table)
                for table in tables:
                    grouped_windows.setdefault((table, window_start.strftime("%Y%m")), []).append(
                        (window_start, window_end)
                    )
            for (table, _), month_windows in grouped_windows.items():
                month_start, month_end = month_windows[0][0], month_windows[-1][1]
                for window_start, count in window_counts(
                    connection,
                    [table],
                    list(mapping[source.source_server_id]),
                    month_start,
                    month_end,
                ).items():
                    source_counts[window_start] = max(source_counts.get(window_start, 0), count)
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
