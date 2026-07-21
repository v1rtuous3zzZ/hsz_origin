"""正式门架同步入口。"""

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Lock

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.batch_log import finish_batch, start_batch
from app.etl.checkpoint import advance
from app.etl.config import EtlSettings
from app.etl.fact_builder import rebuild
from app.etl.match_writer import write_matches
from app.etl.normalizer import normalize
from app.etl.ods_writer import ensure_month_tables, write_events
from app.etl.rule_matcher import match
from app.etl.source_config import load_mapping, load_rules, load_sources
from app.etl.source_reader import (
    incomplete_realtime_physical_codes,
    inspect_remote,
    read_rows,
    source_connection,
)
from app.etl.source_schema import monthly_table, resolve_columns

logger = logging.getLogger("hsz.etl")
settings = EtlSettings()
_source_columns: dict[tuple[str, str], dict[str, str]] = {}
_source_columns_lock = Lock()


def sync_window(
    start: datetime,
    end: datetime,
    server_code: str | None = None,
    source_modes: dict[str, str] | None = None,
    rebuild_facts: bool = True,
) -> dict:
    """从可达门架源库同步一个单月窗口到中心库。"""
    if start >= end or start.strftime("%Y%m") != (end - datetime.resolution).strftime("%Y%m"):
        raise ValueError("正式同步必须使用同月且结束时间晚于开始时间的窗口")
    last_error = None
    for attempt in range(1, 3):
        try:
            return _sync_window(start, end, server_code, source_modes or {}, rebuild_facts)
        except Exception as error:
            last_error = error
            logger.exception("window=%s~%s attempt=%s failed", start, end, attempt)
    return {
        "status": "FAILED",
        "error": str(last_error)[:2000],
        "attempt_count": 2,
    }


def _sync_window(
    start: datetime,
    end: datetime,
    server_code: str | None,
    source_modes: dict[str, str],
    rebuild_facts: bool,
) -> dict:
    metrics = Counter()
    with SessionLocal.begin() as db:
        batch_id, batch_no = start_batch(db, "LIVE_SYNC", "INCREMENTAL", start, end)
    completed_sources = []
    try:
        with SessionLocal.begin() as db:
            ensure_month_tables(db, start.strftime("%Y%m"))
            mapping, rules = load_mapping(db), load_rules(db)
            sources = [
                (source, mapping[source.source_server_id])
                for source in load_sources(db, server_code)
                if mapping.get(source.source_server_id)
            ]
        with ThreadPoolExecutor(max_workers=min(settings.max_workers, len(sources))) as executor:
            collected = list(
                executor.map(
                    lambda item: _collect_source(
                        item[0], item[1], start, end, source_modes.get(item[0].server_code, "AUTO")
                    ),
                    sources,
                )
            )
        with SessionLocal.begin() as db:
            failed_sources = []
            resolved_modes = {}
            for source, source_metrics, events, error, resolved_mode in collected:
                db.execute(
                    text(
                        "INSERT INTO t_etl_batch_source (batch_id,source_server_id,actual_start,actual_end) VALUES (:batch,:source,:start,:end)"
                    ),
                    {
                        "batch": batch_id,
                        "source": source.source_server_id,
                        "start": start,
                        "end": end,
                    },
                )
                if error:
                    db.execute(
                        text(
                            "UPDATE t_etl_batch_source SET status='FAILED',finished_at=NOW(3),error_count=1,error_summary=:error WHERE batch_id=:batch AND source_server_id=:source"
                        ),
                        {"batch": batch_id, "source": source.source_server_id, "error": error},
                    )
                    metrics["error_count"] += 1
                    failed_sources.append(source.server_code)
                    continue
                source_metrics["matched_event_count"] = _write(db, events, rules, batch_id)
                db.execute(
                    text(
                        "UPDATE t_etl_batch_source SET status='SUCCESS',finished_at=NOW(3),source_row_count=:rows,success_event_count=:success,matched_event_count=:matched WHERE batch_id=:batch AND source_server_id=:source"
                    ),
                    {
                        "batch": batch_id,
                        "source": source.source_server_id,
                        "rows": source_metrics["source_row_count"],
                        "success": source_metrics["success_event_count"],
                        "matched": source_metrics["matched_event_count"],
                    },
                )
                metrics += source_metrics
                completed_sources.append(source.source_server_id)
                resolved_modes[source.server_code] = resolved_mode
            if rebuild_facts:
                rebuild(db, start, end, batch_id)
            for source_server_id in completed_sources:
                advance(db, "LIVE_SYNC", source_server_id, end, batch_id)
            status = "PARTIAL" if failed_sources else "SUCCESS"
            error = f"失败源服务器：{','.join(failed_sources)}" if failed_sources else None
            finish_batch(db, batch_id, status, metrics, error)
    except Exception as error:
        logger.exception("batch=%s failed", batch_no)
        with SessionLocal.begin() as db:
            finish_batch(db, batch_id, "FAILED", metrics, str(error)[:2000])
        raise
    return {
        "batch_id": batch_id,
        "batch_no": batch_no,
        "status": status,
        "source_modes": resolved_modes,
        **metrics,
    }


def _collect_source(source, physical, start: datetime, end: datetime, mode: str):
    last_error = None
    tables = []
    for attempt in range(1, 3):
        logger.info("source=%s start=%s end=%s attempt=%s", source.server_code, start, end, attempt)
        connection = None
        try:
            connection = source_connection(source)
            tables = []
            if mode != "HISTORY":
                table = source.current_table_name
                columns = _resolved_source_columns(connection, source.server_code, table)
                realtime_rows = list(
                    read_rows(connection, table, columns, list(physical), start, end, 1000)
                )
                tables.append((table, realtime_rows))
            else:
                realtime_rows = []
            history_physical = (
                list(physical)
                if mode == "HISTORY"
                else incomplete_realtime_physical_codes(realtime_rows, list(physical), start, end)
            )
            resolved_mode = "HISTORY" if history_physical else "REALTIME"
            if history_physical:
                history_table = monthly_table(source.monthly_table_pattern, start)
                if not history_table:
                    raise RuntimeError("源库缺少窗口对应的历史月表")
                columns = _resolved_source_columns(connection, source.server_code, history_table)
                tables.append(
                    (
                        history_table,
                        list(
                            read_rows(
                                connection,
                                history_table,
                                columns,
                                history_physical,
                                start,
                                end,
                                1000,
                            )
                        ),
                    )
                )
            break
        except Exception as error:
            last_error = error
            logger.warning("source=%s attempt=%s failed: %s", source.server_code, attempt, error)
        finally:
            if connection:
                connection.close()
    else:
        return source, Counter(), [], f"源读取重试两次失败：{last_error}"[:2000], mode

    metrics = Counter()
    events = []
    seen_trade_ids = set()
    try:
        for table, rows in tables:
            for row in rows:
                metrics["source_row_count"] += 1
                trade_id = str(row["trade_id"])
                if trade_id in seen_trade_ids:
                    continue
                seen_trade_ids.add(trade_id)
                event = normalize(
                    row,
                    source_server_id=source.source_server_id,
                    source_table_name=table,
                    physical_mapping=physical,
                    policy="MEDIA_SPECIFIC",
                )
                events.append(event)
                if event.success_flag:
                    metrics["success_event_count"] += 1
    except Exception as error:
        return source, Counter(), [], f"源数据转换失败：{error}"[:2000], resolved_mode
    return source, metrics, events, None, resolved_mode


def _resolved_source_columns(connection, server_code: str, table: str) -> dict[str, str]:
    key = (server_code, table)
    with _source_columns_lock:
        cached = _source_columns.get(key)
    if cached is not None:
        return cached
    columns, _ = inspect_remote(connection, table)
    resolved = resolve_columns(columns)
    with _source_columns_lock:
        return _source_columns.setdefault(key, resolved)


def _write(db, events, rules, batch_id) -> int:
    if not events:
        return 0
    write_events(db, events, batch_id)
    matched_count = 0
    pending_matches = []
    for event in events:
        if not event.success_flag:
            continue
        matched = match(event, rules)
        pending_matches.extend((event, rule) for rule in matched)
        matched_count += len(matched)
        if len(pending_matches) >= 5000:
            write_matches(db, pending_matches, batch_id)
            pending_matches.clear()
    write_matches(db, pending_matches, batch_id)
    return matched_count
