"""正式门架同步入口。

同步严格拆成两个阶段：

1. 门架采集阶段：每个源只读、独立重试，读取完成立即关闭连接；
2. 中心处理阶段：标准化、去重、ODS/命中写入、事实重建和日志更新。

中心库处理失败时复用已采集的内存快照，不会再次访问门架服务器。
"""

import logging
import time
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
from app.etl.source_coverage import successful_server_codes
from app.etl.source_lock import source_read_lock
from app.etl.source_reader import (
    inspect_remote,
    is_transient_source_error,
    read_rows,
    source_connection,
    validate_query_index,
)
from app.etl.source_schema import monthly_table, resolve_columns

logger = logging.getLogger("hsz.etl")
settings = EtlSettings()
_source_columns: dict[tuple[str, str], dict[str, str]] = {}
_source_columns_lock = Lock()
_host_locks: dict[str, Lock] = {}
_host_locks_lock = Lock()


def sync_window(
    start: datetime,
    end: datetime,
    server_code: str | None = None,
    source_modes: dict[str, str] | None = None,
    rebuild_facts: bool = True,
    *,
    job_code: str = "LIVE_SYNC",
    job_type: str = "INCREMENTAL",
    source_batch_size: int | None = None,
    max_workers: int | None = None,
    source_retries: int | None = None,
    center_retries: int | None = None,
    default_source_mode: str = "AUTO",
    skip_successful_sources: bool = True,
) -> dict:
    """同步一个单月窗口；源读取与中心库处理使用独立重试边界。"""
    if start >= end or start.strftime("%Y%m") != (end - datetime.resolution).strftime("%Y%m"):
        raise ValueError("正式同步必须使用同月且结束时间晚于开始时间的窗口")

    source_modes = source_modes or {}
    source_batch_size = source_batch_size or settings.batch_size
    max_workers = max_workers or settings.max_workers
    source_retries = source_retries or settings.source_retries
    center_retries = center_retries or settings.center_retries

    with SessionLocal.begin() as db:
        ensure_month_tables(db, start.strftime("%Y%m"))
        mapping, rules = load_mapping(db), load_rules(db)
        sources = [
            (source, mapping[source.source_server_id])
            for source in load_sources(db, server_code)
            if mapping.get(source.source_server_id)
        ]

    if not sources:
        error = "没有可同步且已配置物理门架的源服务器"
        return {"status": "FAILED", "error": error}

    try:
        with source_read_lock(
            settings.source_lock_timeout_seconds,
            enabled=settings.serialize_source_reads,
        ):
            if skip_successful_sources:
                successful = successful_server_codes(start, end)
                sources = [
                    item for item in sources if item[0].server_code not in successful
                ]
                if not sources:
                    return {
                        "status": "SKIPPED",
                        "reason": "等待门架读取锁期间该窗口已由其他任务完成",
                        "window_start": start,
                        "window_end": end,
                    }
            with SessionLocal.begin() as db:
                batch_id, batch_no = start_batch(db, job_code, job_type, start, end)
            collected = _collect_sources(
                sources,
                start,
                end,
                source_modes,
                source_batch_size,
                max_workers,
                source_retries,
                default_source_mode,
            )
    except Exception as error:
        logger.exception("source collection failed")
        message = str(error)[:2000]
        if "batch_id" not in locals():
            return {"status": "FAILED", "error": message, "phase": "SOURCE_COLLECTION"}
        with SessionLocal.begin() as db:
            finish_batch(db, batch_id, "FAILED", {"error_count": 1}, message)
        return {
            "batch_id": batch_id,
            "batch_no": batch_no,
            "status": "FAILED",
            "error": message,
            "phase": "SOURCE_COLLECTION",
        }

    last_error = None
    for center_attempt in range(1, center_retries + 1):
        try:
            result = _persist_collected(
                collected,
                rules,
                start,
                end,
                batch_id,
                batch_no,
                rebuild_facts,
                job_code,
            )
            result["center_attempt_count"] = center_attempt
            return result
        except Exception as error:
            last_error = error
            logger.exception(
                "batch=%s center attempt=%s failed; source snapshot retained",
                batch_no,
                center_attempt,
            )

    message = f"中心库处理重试 {center_retries} 次失败：{last_error}"[:2000]
    with SessionLocal.begin() as db:
        finish_batch(db, batch_id, "FAILED", {"error_count": 1}, message)
    return {
        "batch_id": batch_id,
        "batch_no": batch_no,
        "status": "FAILED",
        "error": message,
        "phase": "CENTER_PROCESSING",
        "center_attempt_count": center_retries,
    }


def _collect_sources(
    sources,
    start: datetime,
    end: datetime,
    source_modes: dict[str, str],
    batch_size: int,
    max_workers: int,
    retries: int,
    default_source_mode: str,
):
    workers = max(1, min(max_workers, len(sources)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda item: _collect_source_serialized_by_host(
                    item[0],
                    item[1],
                    start,
                    end,
                    source_modes.get(item[0].server_code, default_source_mode),
                    batch_size,
                    retries,
                ),
                sources,
            )
        )


def _host_lock(host: str) -> Lock:
    with _host_locks_lock:
        return _host_locks.setdefault(host, Lock())


def _collect_source_serialized_by_host(
    source,
    physical,
    start: datetime,
    end: datetime,
    mode: str,
    batch_size: int,
    retries: int,
):
    # 配置中若多个 source_server 指向同一数据库主机，也只允许串行查询该主机。
    with _host_lock(source.host_address):
        return _collect_source(source, physical, start, end, mode, batch_size, retries)


def _collect_source(
    source,
    physical,
    start: datetime,
    end: datetime,
    mode: str,
    batch_size: int | None = None,
    retries: int | None = None,
):
    """读取一个源快照。返回结构保持兼容：(source, metrics, events, error, mode)。"""
    batch_size = batch_size or settings.batch_size
    retries = retries or settings.source_retries
    last_error = None
    selected_rows: dict[str, tuple[str, dict]] = {}
    raw_row_count = 0
    resolved_mode = mode

    succeeded = False
    for attempt in range(1, retries + 1):
        query_started = time.perf_counter()
        logger.info(
            "source=%s start=%s end=%s attempt=%s",
            source.server_code,
            start,
            end,
            attempt,
        )
        connection = None
        selected_rows = {}
        raw_row_count = 0
        try:
            connection = source_connection(source)
            if mode != "HISTORY":
                current_table = source.current_table_name
                columns = _resolved_source_columns(connection, source.server_code, current_table)
                validate_query_index(
                    connection,
                    source,
                    current_table,
                    columns,
                    required=settings.source_index_live_policy == "FAIL",
                )
                for row in read_rows(
                    connection,
                    current_table,
                    columns,
                    list(physical),
                    start,
                    end,
                    batch_size,
                ):
                    raw_row_count += 1
                    selected_rows.setdefault(str(row["trade_id"]), (current_table, row))

            # AUTO 用于当前月最近窗口，只读实时表。缺少可靠源端水位时，
            # 低流量不能被解释为不完整并触发第二次历史表扫描。
            history_physical = list(physical) if mode in {"HISTORY", "MIXED"} else []
            if history_physical:
                history_table = monthly_table(source.monthly_table_pattern, start)
                if not history_table:
                    raise RuntimeError("源库缺少窗口对应的历史月表")
                columns = _resolved_source_columns(connection, source.server_code, history_table)
                validate_query_index(connection, source, history_table, columns, required=True)
                for row in read_rows(
                    connection,
                    history_table,
                    columns,
                    history_physical,
                    start,
                    end,
                    batch_size,
                ):
                    raw_row_count += 1
                    # 实时表优先；历史表只补实时表没有的 TradeId。
                    selected_rows.setdefault(str(row["trade_id"]), (history_table, row))

            resolved_mode = "REALTIME" if mode == "AUTO" else mode
            succeeded = True
            logger.info(
                "source=%s query_seconds=%.3f rows=%s retries=%s",
                source.server_code,
                time.perf_counter() - query_started,
                raw_row_count,
                attempt - 1,
            )
            break
        except Exception as error:
            last_error = error
            failure_type = type(error).__name__
            transient = is_transient_source_error(error)
            logger.warning(
                "source=%s attempt=%s query_seconds=%.3f failure_type=%s transient=%s error=%s",
                source.server_code,
                attempt,
                time.perf_counter() - query_started,
                failure_type,
                transient,
                error,
            )
            if not transient:
                break
            if attempt < retries:
                time.sleep(2 if attempt == 1 else 5)
        finally:
            if connection:
                connection.close()
    if not succeeded:
        return (
            source,
            Counter(source_attempt_count=attempt),
            [],
            f"源读取 {attempt} 次后失败（{failure_type}）：{last_error}"[:2000],
            mode,
        )

    # 到达这里时门架连接已关闭。后续转换不会延长源库查询连接占用时间。
    metrics = Counter(
        raw_source_row_count=raw_row_count,
        source_row_count=len(selected_rows),
        duplicate_source_row_count=raw_row_count - len(selected_rows),
        source_attempt_count=attempt,
    )
    events = []
    try:
        for table, row in selected_rows.values():
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
        return (
            source,
            metrics,
            [],
            f"源数据转换失败：{error}"[:2000],
            resolved_mode,
        )
    return source, metrics, events, None, resolved_mode


def _persist_collected(
    collected,
    rules,
    start: datetime,
    end: datetime,
    batch_id: int,
    batch_no: str,
    rebuild_facts: bool,
    checkpoint_job_code: str,
) -> dict:
    metrics = Counter()
    completed_sources = []
    resolved_modes = {}
    source_errors = {}

    for source, source_metrics, events, error, resolved_mode in collected:
        with SessionLocal.begin() as db:
            already_successful = db.execute(
                text(
                    "SELECT status FROM t_etl_batch_source "
                    "WHERE batch_id=:batch AND source_server_id=:source"
                ),
                {"batch": batch_id, "source": source.source_server_id},
            ).scalar_one_or_none()
            if already_successful == "SUCCESS":
                completed_sources.append(source.source_server_id)
                resolved_modes[source.server_code] = resolved_mode
                continue

            ensure_month_tables(db, start.strftime("%Y%m"))
            db.execute(
                text(
                    "INSERT INTO t_etl_batch_source "
                    "(batch_id,source_server_id,actual_start,actual_end) "
                    "VALUES (:batch,:source,:start,:end) "
                    "ON DUPLICATE KEY UPDATE status='RUNNING',started_at=NOW(3),"
                    "finished_at=NULL,actual_start=VALUES(actual_start),"
                    "actual_end=VALUES(actual_end),source_row_count=0,"
                    "success_event_count=0,matched_event_count=0,duplicated_count=0,"
                    "error_count=0,error_summary=NULL"
                ),
                {
                    "batch": batch_id,
                    "source": source.source_server_id,
                    "start": start,
                    "end": end,
                },
            )
            if error:
                source_errors[source.server_code] = error
                db.execute(
                    text(
                        "UPDATE t_etl_batch_source SET status='FAILED',finished_at=NOW(3),"
                        "source_row_count=:rows,error_count=1,error_summary=:error "
                        "WHERE batch_id=:batch AND source_server_id=:source"
                    ),
                    {
                        "batch": batch_id,
                        "source": source.source_server_id,
                        "rows": source_metrics["source_row_count"],
                        "error": error,
                    },
                )
                metrics["error_count"] += 1
                continue

            source_metrics["matched_event_count"] = _write(db, events, rules, batch_id)
            db.execute(
                text(
                    "UPDATE t_etl_batch_source SET status='SUCCESS',finished_at=NOW(3),"
                    "source_row_count=:rows,success_event_count=:success,"
                    "matched_event_count=:matched,duplicated_count=:duplicated,"
                    "error_count=0,error_summary=NULL "
                    "WHERE batch_id=:batch AND source_server_id=:source"
                ),
                {
                    "batch": batch_id,
                    "source": source.source_server_id,
                    "rows": source_metrics["source_row_count"],
                    "success": source_metrics["success_event_count"],
                    "matched": source_metrics["matched_event_count"],
                    "duplicated": source_metrics["duplicate_source_row_count"],
                },
            )
            advance(db, checkpoint_job_code, source.source_server_id, end, batch_id)
            metrics += source_metrics
            completed_sources.append(source.source_server_id)
            resolved_modes[source.server_code] = resolved_mode

    if rebuild_facts and completed_sources:
        with SessionLocal.begin() as db:
            ensure_month_tables(db, start.strftime("%Y%m"))
            rebuild(db, start, end, batch_id)

    with SessionLocal.begin() as db:
        summary = db.execute(
            text(
                "SELECT COUNT(*) source_count,"
                "SUM(status='SUCCESS') success_count,SUM(status='FAILED') failed_count,"
                "COALESCE(SUM(source_row_count),0) source_row_count,"
                "COALESCE(SUM(success_event_count),0) success_event_count,"
                "COALESCE(SUM(matched_event_count),0) matched_event_count,"
                "COALESCE(SUM(duplicated_count),0) duplicated_count,"
                "COALESCE(SUM(error_count),0) error_count "
                "FROM t_etl_batch_source WHERE batch_id=:batch"
            ),
            {"batch": batch_id},
        ).mappings().one()
        if summary["failed_count"] and summary["success_count"]:
            status = "PARTIAL"
        elif summary["failed_count"]:
            status = "FAILED"
        elif summary["source_count"] == summary["success_count"]:
            status = "SUCCESS"
        else:
            status = "RUNNING"
        failed_sources = list(
            db.execute(
                text(
                    "SELECT server.server_code FROM t_etl_batch_source source "
                    "JOIN t_source_server server "
                    "ON server.source_server_id=source.source_server_id "
                    "WHERE source.batch_id=:batch AND source.status='FAILED' "
                    "ORDER BY server.server_code"
                ),
                {"batch": batch_id},
            ).scalars()
        )
        error_summary = f"失败源服务器：{','.join(failed_sources)}" if failed_sources else None
        finish_batch(db, batch_id, status, dict(summary), error_summary)

    return {
        "batch_id": batch_id,
        "batch_no": batch_no,
        "status": status,
        "source_modes": resolved_modes,
        "failed_sources": failed_sources,
        "source_errors": source_errors,
        **metrics,
        **dict(summary),
    }


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
    write_events(db, events, batch_id, settings.center_write_batch_size)
    matched_count = 0
    pending_matches = []
    for event in events:
        if not event.success_flag:
            continue
        matched = match(event, rules)
        pending_matches.extend((event, rule) for rule in matched)
        matched_count += len(matched)
        if len(pending_matches) >= settings.center_write_batch_size:
            write_matches(
                db,
                pending_matches,
                batch_id,
                batch_size=settings.center_write_batch_size,
            )
            pending_matches.clear()
    write_matches(
        db,
        pending_matches,
        batch_id,
        batch_size=settings.center_write_batch_size,
    )
    return matched_count
