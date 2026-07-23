"""中心库中的手动同步任务队列，由独立 worker 消费。"""

import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.etl.config import EtlSettings
from app.etl.orchestrator import sync_range

logger = logging.getLogger("hsz.etl.job_queue")
settings = EtlSettings()


@dataclass(frozen=True)
class ManualSyncJob:
    job_id: int
    job_no: str
    window_start: datetime
    window_end: datetime
    window_minutes: int
    sleep_seconds: int
    source_batch_size: int
    max_workers: int
    resume: bool
    continue_on_error: bool
    rebuild_facts: bool
    server_code: str | None


def ensure_job_table(db: Session) -> None:
    """创建中心库任务队列表；不会访问或修改任何门架源库。"""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS t_etl_manual_job (
                job_id BIGINT NOT NULL AUTO_INCREMENT COMMENT '手动同步任务主键',
                job_no VARCHAR(40) NOT NULL COMMENT '手动同步任务编号',
                status VARCHAR(16) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/RUNNING/SUCCESS/PARTIAL/FAILED',
                window_start DATETIME(3) NOT NULL COMMENT '同步区间开始时间',
                window_end DATETIME(3) NOT NULL COMMENT '同步区间结束时间',
                window_minutes INT NOT NULL DEFAULT 120 COMMENT '单个同步窗口分钟数',
                sleep_seconds INT NOT NULL DEFAULT 10 COMMENT '窗口间休眠秒数',
                source_batch_size INT NOT NULL DEFAULT 2000 COMMENT '门架游标单批读取行数',
                max_workers INT NOT NULL DEFAULT 1 COMMENT '不同物理服务器最大并发读取数',
                resume_enabled TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否跳过已有成功源和窗口',
                continue_on_error TINYINT(1) NOT NULL DEFAULT 1 COMMENT '单窗口失败后是否继续',
                rebuild_facts TINYINT(1) NOT NULL DEFAULT 0 COMMENT '明细完成后是否按月重建事实',
                server_code VARCHAR(64) NULL COMMENT '仅同步指定源服务器时的编码',
                created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
                started_at DATETIME(3) NULL COMMENT 'worker 开始执行时间',
                heartbeat_at DATETIME(3) NULL COMMENT 'worker 最近进度时间',
                finished_at DATETIME(3) NULL COMMENT '执行完成时间',
                worker_host VARCHAR(255) NULL COMMENT '执行 worker 主机名',
                worker_pid INT NULL COMMENT '执行 worker 进程号',
                progress_json LONGTEXT NULL COMMENT '最近任务进度 JSON',
                result_json LONGTEXT NULL COMMENT '最终执行结果 JSON',
                error_summary TEXT NULL COMMENT '失败原因摘要',
                PRIMARY KEY (job_id),
                UNIQUE KEY uk_etl_manual_job_no (job_no),
                KEY idx_etl_manual_job_status_created (status, created_at),
                KEY idx_etl_manual_job_window (window_start, window_end)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='手动 ETL 同步后台任务队列'
            """
        )
    )
    columns = set(
        db.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='t_etl_manual_job'"
            )
        ).scalars()
    )
    if "source_batch_size" not in columns:
        db.execute(
            text(
                "ALTER TABLE t_etl_manual_job ADD COLUMN source_batch_size INT NOT NULL "
                "DEFAULT 2000 COMMENT '门架游标单批读取行数' AFTER sleep_seconds"
            )
        )
    if "max_workers" not in columns:
        db.execute(
            text(
                "ALTER TABLE t_etl_manual_job ADD COLUMN max_workers INT NOT NULL "
                "DEFAULT 1 COMMENT '不同物理服务器最大并发读取数' AFTER source_batch_size"
            )
        )


def enqueue_manual_sync(
    db: Session,
    *,
    start: datetime,
    end: datetime,
    window_minutes: int,
    sleep_seconds: int,
    source_batch_size: int,
    max_workers: int,
    resume: bool,
    continue_on_error: bool,
    rebuild_facts: bool,
    server_code: str | None = None,
) -> dict:
    ensure_job_table(db)
    job_no = f"MANUAL-{uuid.uuid4().hex[:16]}"
    result = db.execute(
        text(
            "INSERT INTO t_etl_manual_job "
            "(job_no,window_start,window_end,window_minutes,sleep_seconds,source_batch_size,max_workers,"
            "resume_enabled,continue_on_error,rebuild_facts,server_code) "
            "VALUES (:job_no,:start,:end,:window_minutes,:sleep_seconds,:source_batch_size,:max_workers,"
            ":resume,:continue_on_error,:rebuild_facts,:server_code)"
        ),
        {
            "job_no": job_no,
            "start": start,
            "end": end,
            "window_minutes": window_minutes,
            "sleep_seconds": sleep_seconds,
            "source_batch_size": source_batch_size,
            "max_workers": max_workers,
            "resume": int(resume),
            "continue_on_error": int(continue_on_error),
            "rebuild_facts": int(rebuild_facts),
            "server_code": server_code,
        },
    )
    return {
        "job_id": int(result.lastrowid),
        "job_no": job_no,
        "status": "PENDING",
        "window_start": start,
        "window_end": end,
    }


def get_manual_job(db: Session, job_id: int) -> dict | None:
    ensure_job_table(db)
    row = (
        db.execute(
            text(
                "SELECT job_id,job_no,status,window_start,window_end,window_minutes,"
                "sleep_seconds,source_batch_size,max_workers,resume_enabled,continue_on_error,rebuild_facts,server_code,"
                "created_at,started_at,heartbeat_at,finished_at,worker_host,worker_pid,"
                "progress_json,result_json,error_summary "
                "FROM t_etl_manual_job WHERE job_id=:job_id"
            ),
            {"job_id": job_id},
        )
        .mappings()
        .one_or_none()
    )
    if not row:
        return None
    result = dict(row)
    for field in ("progress_json", "result_json"):
        if result[field]:
            try:
                result[field.removesuffix("_json")] = json.loads(result[field])
            except json.JSONDecodeError:
                result[field.removesuffix("_json")] = result[field]
        result.pop(field)
    return result


def recover_stale_jobs(stale_minutes: int | None = None) -> int:
    stale_minutes = stale_minutes or settings.manual_job_stale_minutes
    cutoff = datetime.now() - timedelta(minutes=stale_minutes)
    with SessionLocal.begin() as db:
        ensure_job_table(db)
        result = db.execute(
            text(
                "UPDATE t_etl_manual_job SET status='PENDING',started_at=NULL,heartbeat_at=NULL,"
                "worker_host=NULL,worker_pid=NULL,error_summary='worker 心跳超时，已重新入队' "
                "WHERE status='RUNNING' AND COALESCE(heartbeat_at,started_at)<:cutoff"
            ),
            {"cutoff": cutoff},
        )
        return int(result.rowcount or 0)


def claim_next_job() -> ManualSyncJob | None:
    with SessionLocal.begin() as db:
        ensure_job_table(db)
        row = (
            db.execute(
                text(
                    "SELECT job_id,job_no,window_start,window_end,window_minutes,sleep_seconds,source_batch_size,max_workers,"
                    "resume_enabled,continue_on_error,rebuild_facts,server_code "
                    "FROM t_etl_manual_job WHERE status='PENDING' "
                    "ORDER BY job_id LIMIT 1 FOR UPDATE SKIP LOCKED"
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            return None
        db.execute(
            text(
                "UPDATE t_etl_manual_job SET status='RUNNING',started_at=NOW(3),"
                "heartbeat_at=NOW(3),worker_host=:host,worker_pid=:pid,error_summary=NULL "
                "WHERE job_id=:job_id"
            ),
            {"job_id": row["job_id"], "host": socket.gethostname(), "pid": os.getpid()},
        )
    return ManualSyncJob(
        job_id=int(row["job_id"]),
        job_no=str(row["job_no"]),
        window_start=row["window_start"],
        window_end=row["window_end"],
        window_minutes=int(row["window_minutes"]),
        sleep_seconds=int(row["sleep_seconds"]),
        source_batch_size=int(row["source_batch_size"]),
        max_workers=int(row["max_workers"]),
        resume=bool(row["resume_enabled"]),
        continue_on_error=bool(row["continue_on_error"]),
        rebuild_facts=bool(row["rebuild_facts"]),
        server_code=row["server_code"],
    )


def update_job_progress(job_id: int, progress: dict) -> None:
    payload = json.dumps(progress, ensure_ascii=False, default=str)
    with SessionLocal.begin() as db:
        db.execute(
            text(
                "UPDATE t_etl_manual_job SET heartbeat_at=NOW(3),progress_json=:progress "
                "WHERE job_id=:job_id AND status='RUNNING'"
            ),
            {"job_id": job_id, "progress": payload},
        )


def finish_job(job_id: int, status: str, result: dict | None, error: str | None = None) -> None:
    payload = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
    with SessionLocal.begin() as db:
        db.execute(
            text(
                "UPDATE t_etl_manual_job SET status=:status,heartbeat_at=NOW(3),"
                "finished_at=NOW(3),result_json=:result,error_summary=:error "
                "WHERE job_id=:job_id"
            ),
            {
                "job_id": job_id,
                "status": status,
                "result": payload,
                "error": error[:2000] if error else None,
            },
        )


def execute_job(job: ManualSyncJob) -> dict:
    logger.info("manual job=%s start", job.job_no)
    try:
        result = sync_range(
            job.window_start,
            job.window_end,
            server_code=job.server_code,
            window_minutes=job.window_minutes,
            sleep_seconds=job.sleep_seconds,
            source_batch_size=job.source_batch_size,
            max_workers=job.max_workers,
            resume=job.resume,
            continue_on_error=job.continue_on_error,
            rebuild_facts=job.rebuild_facts,
            progress_callback=lambda progress: update_job_progress(job.job_id, progress),
        )
    except Exception as error:
        logger.exception("manual job=%s failed", job.job_no)
        finish_job(job.job_id, "FAILED", None, str(error))
        return {
            "job_id": job.job_id,
            "job_no": job.job_no,
            "status": "FAILED",
            "error": str(error),
        }

    status = "SUCCESS" if result["status"] == "SUCCESS" else "PARTIAL"
    finish_job(job.job_id, status, result)
    logger.info("manual job=%s status=%s", job.job_no, status)
    return {
        "job_id": job.job_id,
        "job_no": job.job_no,
        "status": status,
        "result": result,
    }


def run_manual_worker(
    *,
    poll_seconds: int | None = None,
    once: bool = False,
    max_jobs: int | None = None,
) -> dict:
    """持续消费中心库任务；HTTP 进程只负责入队，不执行同步。"""
    poll_seconds = poll_seconds or settings.manual_job_poll_seconds
    recovered = recover_stale_jobs()
    processed = 0
    recent_results = []
    while max_jobs is None or processed < max_jobs:
        job = claim_next_job()
        if job is None:
            if once:
                break
            time.sleep(poll_seconds)
            continue
        recent_results.append(execute_job(job))
        recent_results = recent_results[-100:]
        processed += 1
        if once:
            break
    return {
        "status": "IDLE" if processed == 0 else "SUCCESS",
        "recovered_count": recovered,
        "processed_count": processed,
        "recent_results": recent_results,
    }
