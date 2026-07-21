"""统一调度实时同步和历史循环补数。"""

import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.batch_log import finish_batch, start_batch
from app.etl.config import EtlSettings
from app.etl.fact_builder import rebuild
from app.etl.formal_sync import sync_window
from app.etl.ods_writer import ensure_month_tables

logger = logging.getLogger("hsz.etl.orchestrator")
settings = EtlSettings()
SHANGHAI = ZoneInfo("Asia/Shanghai")


def next_month_start(value: datetime) -> datetime:
    return (value.replace(day=28) + timedelta(days=4)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )


def iter_windows(start: datetime, end: datetime, minutes: int = 120):
    """按固定窗口循环，且任何窗口都不跨月。"""
    if start >= end:
        raise ValueError("结束时间必须晚于开始时间")
    if minutes <= 0:
        raise ValueError("窗口分钟数必须大于 0")
    current = start
    step = timedelta(minutes=minutes)
    while current < end:
        current_end = min(current + step, next_month_start(current), end)
        yield current, current_end
        current = current_end


def aligned_live_window(
    now: datetime | None = None,
    window_minutes: int | None = None,
    safety_delay: timedelta | None = None,
) -> tuple[datetime, datetime]:
    """计算最近一个已经完整结束并经过安全延迟的对齐窗口。"""
    window_minutes = window_minutes or settings.live_window_minutes
    safety_delay = safety_delay if safety_delay is not None else settings.safety_delay
    current = now or datetime.now(SHANGHAI).replace(tzinfo=None)
    if current.tzinfo is not None:
        current = current.astimezone(SHANGHAI).replace(tzinfo=None)
    effective = current - safety_delay
    midnight = effective.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_minutes = int((effective - midnight).total_seconds() // 60)
    aligned_minutes = elapsed_minutes // window_minutes * window_minutes
    end = midnight + timedelta(minutes=aligned_minutes)
    start = end - timedelta(minutes=window_minutes)
    return start, end


def window_was_successful(
    start: datetime,
    end: datetime,
    server_code: str | None = None,
) -> bool:
    """检查窗口是否已成功，避免循环或手动重跑重复访问门架。"""
    with SessionLocal() as db:
        if server_code:
            found = db.execute(
                text(
                    "SELECT 1 FROM t_etl_batch b "
                    "JOIN t_etl_batch_source bs ON bs.batch_id=b.batch_id "
                    "JOIN t_source_server s ON s.source_server_id=bs.source_server_id "
                    "WHERE b.window_start=:start AND b.window_end=:end "
                    "AND bs.status='SUCCESS' AND s.server_code=:server LIMIT 1"
                ),
                {"start": start, "end": end, "server": server_code},
            ).scalar_one_or_none()
        else:
            found = db.execute(
                text(
                    "SELECT 1 FROM t_etl_batch "
                    "WHERE window_start=:start AND window_end=:end "
                    "AND status='SUCCESS' "
                    "AND job_code IN ('LIVE_SYNC','HISTORY_SYNC','MANUAL_SYNC') LIMIT 1"
                ),
                {"start": start, "end": end},
            ).scalar_one_or_none()
    return found is not None


def run_live_once(
    now: datetime | None = None,
    *,
    server_code: str | None = None,
    resume: bool = True,
    source_batch_size: int | None = None,
    max_workers: int | None = None,
) -> dict:
    start, end = aligned_live_window(now)
    if resume and window_was_successful(start, end, server_code):
        return {
            "status": "SKIPPED",
            "reason": "窗口已有成功同步记录",
            "window_start": start,
            "window_end": end,
        }
    return sync_window(
        start,
        end,
        server_code,
        rebuild_facts=True,
        job_code="LIVE_SYNC",
        job_type="INCREMENTAL",
        default_source_mode="AUTO",
        source_batch_size=source_batch_size,
        max_workers=max_workers,
    )


def run_live_loop(
    *,
    poll_seconds: int | None = None,
    server_code: str | None = None,
    max_cycles: int | None = None,
    source_batch_size: int | None = None,
    max_workers: int | None = None,
) -> list[dict]:
    """常驻循环；每次只同步最近一个完整两小时窗口。"""
    poll_seconds = poll_seconds or settings.poll_seconds
    results = []
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        try:
            result = run_live_once(
                server_code=server_code,
                resume=True,
                source_batch_size=source_batch_size,
                max_workers=max_workers,
            )
            if result["status"] != "SKIPPED":
                logger.info("live result=%s", result)
            results.append(result)
        except Exception as error:
            logger.exception("live loop failed: %s", error)
            results.append({"status": "FAILED", "error": str(error)[:2000]})
        if max_cycles is None or cycles < max_cycles:
            time.sleep(poll_seconds)
    return results


def sync_range(
    start: datetime,
    end: datetime,
    *,
    server_code: str | None = None,
    window_minutes: int | None = None,
    sleep_seconds: int | None = None,
    resume: bool = True,
    continue_on_error: bool = True,
    rebuild_facts: bool = True,
    max_windows: int | None = None,
    source_batch_size: int | None = None,
    max_workers: int | None = None,
) -> dict:
    """循环同步历史区间，默认跳过成功窗口并在窗口间短暂休眠。"""
    window_minutes = window_minutes or settings.history_window_minutes
    sleep_seconds = (
        settings.history_sleep_seconds if sleep_seconds is None else sleep_seconds
    )
    windows = list(iter_windows(start, end, window_minutes))
    if max_windows is not None:
        windows = windows[:max_windows]

    results = []
    attempted = failed = skipped = 0
    for index, (window_start, window_end) in enumerate(windows):
        if resume and window_was_successful(window_start, window_end, server_code):
            skipped += 1
            results.append(
                {
                    "status": "SKIPPED",
                    "reason": "窗口已有成功同步记录",
                    "window_start": window_start,
                    "window_end": window_end,
                }
            )
            continue

        # 过去月份直接读月表，避免每个历史窗口先对实时表做一次空查询。
        now = datetime.now(SHANGHAI).replace(tzinfo=None)
        default_source_mode = (
            "HISTORY" if window_start.strftime("%Y%m") < now.strftime("%Y%m") else "AUTO"
        )
        attempted += 1
        result = sync_window(
            window_start,
            window_end,
            server_code,
            rebuild_facts=False,
            job_code="HISTORY_SYNC",
            job_type="BACKFILL",
            default_source_mode=default_source_mode,
            source_batch_size=source_batch_size,
            max_workers=max_workers,
        )
        result.setdefault("window_start", window_start)
        result.setdefault("window_end", window_end)
        results.append(result)
        if result["status"] not in {"SUCCESS", "SKIPPED"}:
            failed += 1
            if not continue_on_error:
                break
        if index < len(windows) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    fact_result = None
    if rebuild_facts and failed == 0:
        fact_result = rebuild_fact_range(start, end)

    return {
        "status": "SUCCESS" if failed == 0 else "PARTIAL",
        "window_count": len(windows),
        "attempted_count": attempted,
        "skipped_count": skipped,
        "failed_count": failed,
        "batches": results,
        "fact_rebuild": fact_result,
    }


def rebuild_fact_range(start: datetime, end: datetime, retries: int | None = None) -> dict:
    """历史明细全部写完后按月统一重建事实，全程只访问中心库。"""
    retries = retries or settings.center_retries
    with SessionLocal.begin() as db:
        batch_id, batch_no = start_batch(db, "FACT_REBUILD", "REBUILD", start, end)

    last_error = None
    for attempt in range(1, retries + 1):
        try:
            with SessionLocal.begin() as db:
                for month_start, month_end in _month_ranges(start, end):
                    ensure_month_tables(db, month_start.strftime("%Y%m"))
                    rebuild(db, month_start, month_end, batch_id)
                finish_batch(db, batch_id, "SUCCESS", {})
            return {
                "batch_id": batch_id,
                "batch_no": batch_no,
                "status": "SUCCESS",
                "attempt_count": attempt,
            }
        except Exception as error:
            last_error = error
            logger.exception("fact rebuild attempt=%s failed", attempt)

    message = f"事实重建重试 {retries} 次失败：{last_error}"[:2000]
    with SessionLocal.begin() as db:
        finish_batch(db, batch_id, "FAILED", {"error_count": 1}, message)
    return {
        "batch_id": batch_id,
        "batch_no": batch_no,
        "status": "FAILED",
        "attempt_count": retries,
        "error": message,
    }


def _month_ranges(start: datetime, end: datetime):
    current = start
    while current < end:
        current_end = min(next_month_start(current), end)
        yield current, current_end
        current = current_end
