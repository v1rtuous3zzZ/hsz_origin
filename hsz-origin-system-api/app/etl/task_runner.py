import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from datetime import time as day_time
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from app.db.session import SessionLocal
from app.etl.fact_builder import rebuild
from app.etl.ods_writer import ensure_month_tables
from app.etl.source_config import load_mapping, load_sources
from app.etl.sync_service import sync_window

SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI).replace(tzinfo=None)


def next_month(value: datetime) -> datetime:
    return (value.replace(day=28) + timedelta(days=4)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def iter_windows(start: datetime, end: datetime, minutes: int = 120):
    current = start
    step = timedelta(minutes=minutes)
    while current < end:
        window_end = min(current + step, next_month(current), end)
        yield current, window_end
        current = window_end


def iter_month_ranges(start: datetime, end: datetime):
    current = start
    while current < end:
        month_end = min(next_month(current), end)
        yield current, month_end
        current = month_end


def aligned_live_window(now: datetime | None = None, minutes: int = 120,
                        safety_delay: timedelta = timedelta(seconds=120)):
    effective = (now or shanghai_now()) - safety_delay
    minute = (effective.hour * 60 + effective.minute) // minutes * minutes
    end = effective.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minute)
    return end - timedelta(minutes=minutes), end


def nightly_ranges(now: datetime | None = None, days: tuple[int, ...] = (1, 2)):
    today = (now or shanghai_now()).date()
    return [
        (datetime.combine(today - timedelta(days=day), day_time.min),
         datetime.combine(today - timedelta(days=day - 1), day_time.min))
        for day in days
    ]


def server_codes(server_code: str | None = None) -> list[str]:
    with SessionLocal() as db:
        sources = load_sources(db, server_code)
        mapped_source_ids = set(load_mapping(db))
        return [
            source.server_code for source in sources
            if source.source_server_id in mapped_source_ids
        ]


def validate_backfill_range(start: datetime, end: datetime,
                            window_minutes: int = 120) -> None:
    if start >= end:
        raise ValueError("结束时间必须晚于开始时间")
    if window_minutes != 120:
        raise ValueError("BACKFILL 固定使用 120 分钟窗口")
    for value in (start, end):
        if value.minute or value.second or value.microsecond or value.hour % 2:
            raise ValueError("BACKFILL 时间必须对齐 Asia/Shanghai 偶数整点两小时边界")
        if value.tzinfo is not None and value.utcoffset() != timedelta(hours=8):
            raise ValueError("BACKFILL 时间必须使用 Asia/Shanghai 语义")


def month_is_complete(month_start: datetime, month_end: datetime, codes: list[str]) -> bool:
    expected_windows = {
        (code, window_start, window_end)
        for code in codes
        for window_start, window_end in iter_windows(month_start, month_end, 120)
    }
    with SessionLocal() as db:
        statement = text("""
            WITH ranked AS (
                SELECT server_code,window_start,window_end,status,check_status,
                       ROW_NUMBER() OVER (
                           PARTITION BY server_code,window_start,window_end
                           ORDER BY sync_log_id DESC
                       ) AS row_no
                FROM t_etl_sync_log
                WHERE window_start>=:start AND window_end<=:end
                  AND server_code IN :codes
            )
            SELECT server_code,window_start,window_end,status,check_status FROM ranked
            WHERE row_no=1 AND status IN ('SUCCESS','SKIPPED')
              AND check_status='COMPLETE'
        """).bindparams(bindparam("codes", expanding=True))
        rows = db.execute(
            statement, {"start": month_start, "end": month_end, "codes": codes}
        ).mappings()
        complete_windows = {
            (
                row["server_code"],
                datetime.fromisoformat(row["window_start"]) if isinstance(
                    row["window_start"], str
                ) else row["window_start"],
                datetime.fromisoformat(row["window_end"]) if isinstance(
                    row["window_end"], str
                ) else row["window_end"],
            )
            for row in rows
        }
    return expected_windows.issubset(complete_windows)


def latest_lineage_id(task_no: str, start: datetime, end: datetime) -> int | None:
    with SessionLocal() as db:
        return db.execute(text(
            "SELECT MAX(sync_log_id) FROM t_etl_sync_log "
            "WHERE task_no=:task AND window_start>=:start AND window_end<=:end"
        ), {"task": task_no, "start": start, "end": end}).scalar_one_or_none()


def rebuild_window(start: datetime, end: datetime, task_no: str) -> None:
    lineage_id = latest_lineage_id(task_no, start, end)
    if lineage_id is None:
        return
    with SessionLocal.begin() as db:
        ensure_month_tables(db, start.strftime("%Y%m"))
        rebuild(db, start, end, lineage_id)


def run_range(start: datetime, end: datetime, *, operation: str = "BACKFILL",
              server_code: str | None = None, window_minutes: int = 120,
              sleep_seconds: int = 5, force: bool = False,
              stop_on_error: bool = False, task_no: str | None = None,
              progress_callback=None, source_mode: str = "auto") -> dict:
    if operation == "BACKFILL":
        validate_backfill_range(start, end, window_minutes)
    elif start >= end:
        raise ValueError("结束时间必须晚于开始时间")
    task_no = task_no or f"{operation}-{uuid.uuid4().hex[:16]}"
    windows = list(iter_windows(start, end, window_minutes))
    codes = server_codes(server_code)
    if not codes:
        raise ValueError("没有找到可采集服务器")
    total = len(windows) * len(codes)
    recent_results = deque(maxlen=100)
    processed, failed, missing, complete = 0, 0, 0, 0
    touched_months: set[str] = set()
    all_codes = server_codes(None)
    if not all_codes:
        raise ValueError("没有找到可采集服务器")
    for window_start, window_end in windows:
        if operation == "BACKFILL":
            touched_months.add(window_start.strftime("%Y%m"))
        window_failed = False
        window_missing = False
        for code in codes:
            result = sync_window(code, window_start, window_end, operation, force,
                                 task_no=task_no, source_mode=source_mode)
            recent_results.append(result)
            processed += 1
            if result["status"] == "FAILED":
                failed += 1
                window_failed = True
            elif result.get("check_status") == "MISSING":
                missing += 1
                window_missing = True
            else:
                complete += 1
            if progress_callback:
                progress_callback({"total_windows": total, "processed_windows": processed,
                                   "complete_windows": complete, "missing_windows": missing,
                                   "failed_windows": failed})
            if window_failed and stop_on_error:
                break
            if processed < total and sleep_seconds:
                time.sleep(sleep_seconds)
        if operation == "LIVE" and not window_failed and not window_missing:
            rebuild_window(window_start, window_end, task_no)
        if window_failed and stop_on_error:
            break
    rebuilt = []
    if operation == "REPAIR" and failed == 0 and missing == 0:
        for month_start, month_end in iter_month_ranges(start, end):
            rebuild_window(month_start, month_end, task_no)
            rebuilt.append(month_start.strftime("%Y%m"))
    if operation == "BACKFILL":
        for month in sorted(touched_months):
            month_start = datetime.strptime(month, "%Y%m")
            month_end = next_month(month_start)
            if not month_is_complete(month_start, month_end, all_codes):
                continue
            rebuild_window(month_start, month_end, task_no)
            rebuilt.append(month)
    return {"task_no": task_no, "status": "SUCCESS" if failed == 0 else "PARTIAL",
            "total_windows": total, "processed_windows": processed,
            "complete_windows": complete, "missing_windows": missing,
            "failed_windows": failed, "rebuilt_months": rebuilt,
            "recent_results": list(recent_results)}


def run_nightly_check(*, now: datetime | None = None, days=(1, 2),
                      server_code: str | None = None, sleep_seconds: int = 5,
                      source_mode: str = "auto") -> dict:
    results = []
    task_no = f"CHECK-{uuid.uuid4().hex[:16]}"
    for start, end in nightly_ranges(now, tuple(days)):
        results.append(run_range(start, end, operation="CHECK", server_code=server_code,
                                 sleep_seconds=sleep_seconds, task_no=task_no,
                                 source_mode=source_mode))
    return {"task_no": task_no, "status": "SUCCESS" if all(
        item["status"] == "SUCCESS" for item in results) else "PARTIAL", "days": results}


def repair_by_sync_id(sync_id: str) -> dict:
    with SessionLocal() as db:
        row = db.execute(text(
            "SELECT server_code,window_start,window_end FROM t_etl_sync_log WHERE sync_id=:id"
        ), {"id": sync_id}).mappings().one_or_none()
    if not row:
        raise ValueError("同步日志不存在")
    return sync_window(row["server_code"], row["window_start"], row["window_end"],
                       "REPAIR", True)
