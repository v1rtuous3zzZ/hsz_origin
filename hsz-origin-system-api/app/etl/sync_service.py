import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal
from app.etl.center_writer import normalize_rows, write_snapshot
from app.etl.config import EtlSettings
from app.etl.source_config import load_mapping, load_rules, load_sources
from app.etl.source_reader import read_source_snapshot
from app.etl.source_schema import source_tables
from app.etl.sync_log import finish_sync, latest_complete, start_sync
from app.etl.verifier import center_trade_ids, missing_trade_ids

OPERATIONS = {"LIVE", "BACKFILL", "REPAIR", "CHECK"}
settings = EtlSettings()


def should_skip(operation: str, force: bool, complete: bool) -> bool:
    return operation in {"LIVE", "BACKFILL"} and not force and complete


def write_with_retry(events, rules, sync_log_id: int) -> dict:
    """中心重试只使用调用方已读取并标准化的内存快照。"""
    for attempt in range(1, settings.center_retries + 2):
        try:
            with SessionLocal.begin() as db:
                return write_snapshot(
                    db, events, rules, sync_log_id, settings.center_write_batch_size
                )
        except Exception:
            if attempt > settings.center_retries:
                raise
            time.sleep(2 if attempt == 1 else 5)
    raise AssertionError("unreachable")


def sync_window(server_code: str, start: datetime, end: datetime, operation: str,
                force: bool = False, *, task_no: str | None = None,
                source_mode: str = "auto") -> dict:
    """处理一个门架服务器和一个不跨月时间窗口。"""
    operation = operation.upper()
    if operation not in OPERATIONS:
        raise ValueError("operation 必须是 LIVE、BACKFILL、REPAIR 或 CHECK")
    if start >= end or start.strftime("%Y%m") != (end.replace(microsecond=0) - __import__("datetime").timedelta(microseconds=1)).strftime("%Y%m"):
        raise ValueError("同步窗口必须结束晚于开始且不能跨月")
    task_no = task_no or f"{operation}-{uuid.uuid4().hex[:16]}"
    with SessionLocal() as db:
        sources = load_sources(db, server_code)
        mapping, rules = load_mapping(db), load_rules(db)
    if len(sources) != 1 or not mapping.get(sources[0].source_server_id):
        raise ValueError(f"找不到唯一且可采集的源服务器：{server_code}")
    server = sources[0]
    shanghai_now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    tables = source_tables(server, start, end, shanghai_now, source_mode)
    table_label = ",".join(tables)
    started = time.perf_counter()
    with SessionLocal.begin() as db:
        sync_log_id, sync_id = start_sync(
            db, task_no=task_no, operation=operation, server=server, start=start, end=end
        )
        if should_skip(operation, force, latest_complete(db, server_code, start, end)):
            finish_sync(db, sync_id, status="SKIPPED", check_status="COMPLETE",
                        source_table=table_label, error_message="已存在完整同步记录",
                        total_duration_ms=round((time.perf_counter() - started) * 1000))
            return {"sync_id": sync_id, "status": "SKIPPED", "check_status": "COMPLETE"}
    try:
        rows, source_metrics = read_source_snapshot(
            server, tables, list(mapping[server.source_server_id]), start, end,
            check_only=operation == "CHECK", batch_size=settings.batch_size,
            retries=settings.source_retries,
        )
        source_ids = {str(row["trade_id"]) for row in rows}
        write_metrics = {"inserted_count": 0, "updated_count": 0, "write_duration_ms": 0}
        if operation != "CHECK":
            events = normalize_rows(rows, server=server, table=table_label,
                                    physical_mapping=mapping[server.source_server_id])
            write_metrics = write_with_retry(events, rules, sync_log_id)
        verify_started = time.perf_counter()
        with SessionLocal.begin() as db:
            found = center_trade_ids(db, source_ids, start.strftime("%Y%m"))
            missing = missing_trade_ids(source_ids, found)
            check_status = "COMPLETE" if not missing else "MISSING"
            finish_sync(
                db, sync_id, status="SUCCESS", check_status=check_status,
                source_table=table_label, source_unique_count=len(source_ids),
                center_matched_count=len(found), missing_count=len(missing),
                duplicate_count=source_metrics["duplicate_count"],
                query_duration_ms=source_metrics["query_duration_ms"],
                verify_duration_ms=round((time.perf_counter() - verify_started) * 1000),
                total_duration_ms=round((time.perf_counter() - started) * 1000),
                missing_ids=missing, **write_metrics,
            )
        return {"sync_id": sync_id, "task_no": task_no, "operation": operation,
                "server_code": server_code, "source_table": table_label, "status": "SUCCESS",
                "check_status": check_status, "source_unique_count": len(source_ids),
                "center_matched_count": len(found), "missing_count": len(missing),
                **source_metrics, **write_metrics}
    except Exception as error:
        with SessionLocal.begin() as db:
            finish_sync(db, sync_id, status="FAILED", error_type=type(error).__name__,
                        error_message=str(error)[:2000], source_table=table_label,
                        total_duration_ms=round((time.perf_counter() - started) * 1000))
        return {"sync_id": sync_id, "task_no": task_no, "status": "FAILED",
                "error_type": type(error).__name__, "error": str(error)}
