"""统一调度实时同步、历史循环补数和事实重建。"""

import logging
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.batch_log import finish_batch, start_batch
from app.etl.config import EtlSettings
from app.etl.fact_builder import rebuild
from app.etl.formal_sync import sync_window
from app.etl.ods_writer import ensure_month_tables
from app.etl.source_config import load_mapping, load_sources

logger = logging.getLogger("hsz.etl.orchestrator")
settings = EtlSettings()
ProgressCallback = Callable[[dict], None]


def shanghai_timezone() -> ZoneInfo:
    """延迟加载时区，避免模块导入阶段依赖系统 zoneinfo 数据。"""
    return ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(shanghai_timezone()).replace(tzinfo=None)


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
    current = now or shanghai_now()
    if current.tzinfo is not None:
        current = current.astimezone(shanghai_timezone()).replace(tzinfo=None)
    effective = current - safety_delay
    midnight = effective.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_minutes = int((effective - midnight).total_seconds() // 60)
    aligned_minutes = elapsed_minutes // window_minutes * window_minutes
    end = midnight + timedelta(minutes=aligned_minutes)
    start = end - timedelta(minutes=window_minutes)
    return start, end


def expected_server_codes(server_code: str | None = None) -> set[str]:
    with SessionLocal() as db:
        mapping = load_mapping(db)
        return {
            source.server_code
            for source in load_sources(db, server_code)
            if mapping.get(source.source_server_id)
        }


def successful_server_codes(start: datetime, end: datetime) -> set[str]:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT DISTINCT server.server_code FROM t_etl_batch_source source "
                "JOIN t_etl_batch batch ON batch.batch_id=source.batch_id "
                "JOIN t_source_server server "
                "ON server.source_server_id=source.source_server_id "
                "WHERE batch.window_start=:start AND batch.window_end=:end "
                "AND source.status='SUCCESS'"
            ),
            {"start": start, "end": end},
        ).scalars()
        return set(rows)


def missing_server_codes(
    start: datetime, end: datetime, server_code: str | None = None
) -> list[str]:
    expected = expected_server_codes(server_code)
    successful = successful_server_codes(start, end)
    return sorted(expected - successful)


def window_was_successful(
    start: datetime,
    end: datetime,
    server_code: str | None = None,
) -> bool:
    """允许多个补偿批次共同覆盖窗口，避免反复读取已成功源服务器。"""
    expected = expected_server_codes(server_code)
    return bool(expected) and not (expected - successful_server_codes(start, end))


def _sync_resumable_window(
    start: datetime,
    end: datetime,
    *,
    server_code: str | None,
    resume: bool,
    rebuild_facts: bool,
    job_code: str,
    job_type: str,
    default_source_mode: str,
    source_batch_size: int | None,
    max_workers: int | None,
) -> dict:
    if server_code:
        if resume and window_was_successful(start, end, server_code):
            return {
                "status": "SKIPPED",
                "reason": "指定源服务器在该窗口已有成功记录",
                "window_start": start,
                "window_end": end,
                "server_code": server_code,
            }
        return sync_window(
            start,
            end,
            server_code,
            rebuild_facts=rebuild_facts,
            job_code=job_code,
            job_type=job_type,
            default_source_mode=default_source_mode,
            source_batch_size=source_batch_size,
            max_workers=1,
        )

    if not resume:
        return sync_window(
            start,
            end,
            rebuild_facts=rebuild_facts,
            job_code=job_code,
            job_type=job_type,
            default_source_mode=default_source_mode,
            source_batch_size=source_batch_size,
            max_workers=max_workers,
        )

    expected = expected_server_codes()
    if not expected:
        return sync_window(
            start,
            end,
            rebuild_facts=rebuild_facts,
            job_code=job_code,
            job_type=job_type,
            default_source_mode=default_source_mode,
            source_batch_size=source_batch_size,
            max_workers=max_workers,
        )

    missing = missing_server_codes(start, end)
    if not missing:
        return {
            "status": "SKIPPED",
            "reason": "窗口的所有源服务器均已有成功记录",
            "window_start": start,
            "window_end": end,
        }
    if set(missing) == expected:
        return sync_window(
            start,
            end,
            rebuild_facts=rebuild_facts,
            job_code=job_code,
            job_type=job_type,
            default_source_mode=default_source_mode,
            source_batch_size=source_batch_size,
            max_workers=max_workers,
        )

    results = []
    for missing_server in missing:
        results.append(
            sync_window(
                start,
                end,
                missing_server,
                rebuild_facts=False,
                job_code=job_code,
                job_type=job_type,
                default_source_mode=default_source_mode,
                source_batch_size=source_batch_size,
                max_workers=1,
            )
        )
    failed = [result for result in results if result["status"] != "SUCCESS"]
    fact_result = None
    if not failed and rebuild_facts:
        fact_result = rebuild_fact_range(start, end)
    return {
        "status": "SUCCESS" if not failed else "PARTIAL",
        "window_start": start,
        "window_end": end,
        "repaired_servers": missing,
        "batches": results,
        "fact_rebuild": fact_result,
    }


def run_live_once(
    now: datetime | None = None,
    *,
    server_code: str | None = None,
    resume: bool = True,
    source_batch_size: int | None = None,
    max_workers: int | None = None,
) -> dict:
    start, end = aligned_live_window(now)
    return _sync_resumable_window(
        start,
        end,
        server_code=server_code,
        resume=resume,
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
    results = deque(maxlen=max_cycles or 100)
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
    return list(results)


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
    progress_callback: ProgressCallback | None = None,
    result_limit: int = 100,
) -> dict:
    """循环同步历史区间；结果只保留最近若干窗口，避免长任务占满内存。"""
    window_minutes = window_minutes or settings.history_window_minutes
    sleep_seconds = (
        settings.history_sleep_seconds if sleep_seconds is None else sleep_seconds
    )
    windows = list(iter_windows(start, end, window_minutes))
    if max_windows is not None:
        windows = windows[:max_windows]

    results = deque(maxlen=max(1, result_limit))
    attempted = failed = skipped = 0
    processed_end = start
    for index, (window_start, window_end) in enumerate(windows):
        default_source_mode = (
            "HISTORY"
            if window_start.strftime("%Y%m") < shanghai_now().strftime("%Y%m")
            else "AUTO"
        )
        attempted += 1
        result = _sync_resumable_window(
            window_start,
            window_end,
            server_code=server_code,
            resume=resume,
            rebuild_facts=False,
            job_code="HISTORY_SYNC",
            job_type="BACKFILL",
            default_source_mode=default_source_mode,
            source_batch_size=source_batch_size,
            max_workers=max_workers,
        )
        if result["status"] == "SKIPPED":
            skipped += 1
            attempted -= 1
        result.setdefault("window_start", window_start)
        result.setdefault("window_end", window_end)
        results.append(result)
        processed_end = window_end
        if result["status"] not in {"SUCCESS", "SKIPPED"}:
            failed += 1
        progress = {
            "window_count": len(windows),
            "processed_count": index + 1,
            "attempted_count": attempted,
            "skipped_count": skipped,
            "failed_count": failed,
            "last_window_start": window_start,
            "last_window_end": window_end,
            "last_status": result["status"],
        }
        if progress_callback:
            progress_callback(progress)
        if failed and not continue_on_error:
            break
        if index < len(windows) - 1 and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    fact_result = None
    if rebuild_facts and failed == 0 and processed_end > start:
        fact_result = rebuild_fact_range(start, processed_end)
        if progress_callback:
            progress_callback(
                {
                    "window_count": len(windows),
                    "processed_count": len(windows),
                    "attempted_count": attempted,
                    "skipped_count": skipped,
                    "failed_count": failed,
                    "fact_rebuild": fact_result,
                }
            )

    return {
        "status": "SUCCESS" if failed == 0 else "PARTIAL",
        "window_count": len(windows),
        "processed_count": attempted + skipped + failed,
        "attempted_count": attempted,
        "skipped_count": skipped,
        "failed_count": failed,
        "recent_batches": list(results),
        "fact_rebuild": fact_result,
    }


def rebuild_fact_range(start: datetime, end: datetime, retries: int | None = None) -> dict:
    """历史明细全部写完后按月独立事务重建事实，全程只访问中心库。"""
    retries = retries or settings.center_retries
    with SessionLocal.begin() as db:
        batch_id, batch_no = start_batch(db, "FACT_REBUILD", "REBUILD", start, end)

    rebuilt_months = []
    for month_start, month_end in _month_ranges(start, end):
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                with SessionLocal.begin() as db:
                    ensure_month_tables(db, month_start.strftime("%Y%m"))
                    rebuild(db, month_start, month_end, batch_id)
                rebuilt_months.append(month_start.strftime("%Y%m"))
                break
            except Exception as error:
                last_error = error
                logger.exception(
                    "fact rebuild month=%s attempt=%s failed",
                    month_start.strftime("%Y%m"),
                    attempt,
                )
        else:
            message = (
                f"月份 {month_start:%Y%m} 事实重建重试 {retries} 次失败：{last_error}"
            )[:2000]
            with SessionLocal.begin() as db:
                finish_batch(db, batch_id, "FAILED", {"error_count": 1}, message)
            return {
                "batch_id": batch_id,
                "batch_no": batch_no,
                "status": "FAILED",
                "failed_month": month_start.strftime("%Y%m"),
                "rebuilt_months": rebuilt_months,
                "error": message,
            }

    with SessionLocal.begin() as db:
        finish_batch(db, batch_id, "SUCCESS", {})
    return {
        "batch_id": batch_id,
        "batch_no": batch_no,
        "status": "SUCCESS",
        "rebuilt_months": rebuilt_months,
    }


def _month_ranges(start: datetime, end: datetime):
    current = start
    while current < end:
        current_end = min(next_month_start(current), end)
        yield current, current_end
        current = current_end
