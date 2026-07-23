"""中心库单 worker 任务队列。"""

import json
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.config import EtlSettings
from app.etl.source_config import load_mapping, load_sources
from app.etl.task_runner import run_range, validate_backfill_range

settings = EtlSettings()


@dataclass(frozen=True)
class EtlJob:
    job_id: int
    task_no: str
    operation: str
    window_start: object
    window_end: object
    server_code: str | None
    force: bool
    window_minutes: int
    sleep_seconds: int
    stop_on_error: bool
    source_mode: str


def enqueue_job(db, *, operation: str, start, end, server_code: str | None = None,
                force: bool = False, window_minutes: int = 120, sleep_seconds: int = 5,
                stop_on_error: bool = False, source_mode: str = "auto") -> dict:
    if operation == "BACKFILL":
        validate_backfill_range(start, end, window_minutes)
    elif start >= end:
        raise ValueError("结束时间必须晚于开始时间")
    sources = load_sources(db, server_code)
    mapped_source_ids = set(load_mapping(db))
    if not any(source.source_server_id in mapped_source_ids for source in sources):
        raise ValueError("没有找到可采集服务器")
    if operation == "LIVE":
        existing = db.execute(text(
            "SELECT job_id,task_no,status FROM t_etl_manual_job "
            "WHERE operation='LIVE' AND window_start=:start AND window_end=:end "
            "AND COALESCE(server_code,'')=COALESCE(:server,'') "
            "AND status IN ('PENDING','RUNNING') ORDER BY job_id DESC LIMIT 1"
        ), {"start": start, "end": end, "server": server_code}).mappings().one_or_none()
        if existing:
            return dict(existing)
    task_no = f"{operation}-{uuid.uuid4().hex[:16]}"
    result = db.execute(text(
        "INSERT INTO t_etl_manual_job "
        "(task_no,operation,status,window_start,window_end,server_code,force_enabled,"
        "window_minutes,sleep_seconds,stop_on_error,source_mode) "
        "VALUES (:task,:operation,'PENDING',:start,:end,:server,:force,:minutes,:sleep,:stop,:mode)"
    ), {"task": task_no, "operation": operation, "start": start, "end": end,
        "server": server_code, "force": int(force), "minutes": window_minutes,
        "sleep": sleep_seconds, "stop": int(stop_on_error), "mode": source_mode})
    return {"job_id": int(result.lastrowid), "task_no": task_no, "status": "PENDING"}


def get_job(db, job_id: int) -> dict | None:
    row = db.execute(text(
        "SELECT job_id,task_no,operation,status,window_start,window_end,server_code,"
        "total_windows,processed_windows,complete_windows,missing_windows,failed_windows,"
        "created_at,started_at,finished_at,error_message FROM t_etl_manual_job "
        "WHERE job_id=:id"
    ), {"id": job_id}).mappings().one_or_none()
    return dict(row) if row else None


def claim_next_job() -> EtlJob | None:
    with SessionLocal.begin() as db:
        row = db.execute(text(
            "SELECT job_id,task_no,operation,window_start,window_end,server_code,force_enabled "
            ",window_minutes,sleep_seconds,stop_on_error,source_mode "
            "FROM t_etl_manual_job WHERE status='PENDING' ORDER BY "
            "CASE operation WHEN 'LIVE' THEN 1 WHEN 'REPAIR' THEN 2 "
            "WHEN 'CHECK' THEN 3 WHEN 'BACKFILL' THEN 4 ELSE 5 END, "
            "job_id LIMIT 1 FOR UPDATE"
        )).mappings().one_or_none()
        if not row:
            return None
        db.execute(text(
            "UPDATE t_etl_manual_job SET status='RUNNING',started_at=NOW(3) WHERE job_id=:id"
        ), {"id": row["job_id"]})
    return EtlJob(int(row["job_id"]), row["task_no"], row["operation"],
                  row["window_start"], row["window_end"], row["server_code"],
                  bool(row["force_enabled"]), int(row["window_minutes"]),
                  int(row["sleep_seconds"]), bool(row["stop_on_error"]), row["source_mode"])


def recover_running_jobs() -> int:
    with SessionLocal.begin() as db:
        db.execute(text(
            "UPDATE t_etl_sync_log SET status='FAILED',check_status='UNCHECKED',"
            "finished_at=NOW(3),error_type='WorkerRestart',"
            "error_message='worker重启，窗口执行中断' WHERE status='RUNNING'"
        ))
        result = db.execute(text(
            "UPDATE t_etl_manual_job SET status='PENDING',started_at=NULL,"
            "finished_at=NULL,error_message='worker 重启，任务重新入队' "
            "WHERE status='RUNNING'"
        ))
        return int(result.rowcount or 0)


def _progress(job_id: int, values: dict) -> None:
    fields = ("total_windows", "processed_windows", "complete_windows",
              "missing_windows", "failed_windows")
    with SessionLocal.begin() as db:
        db.execute(text("UPDATE t_etl_manual_job SET " + ",".join(
            f"{field}=:{field}" for field in fields
        ) + " WHERE job_id=:job_id"), {"job_id": job_id, **{f: values.get(f, 0) for f in fields}})


def execute_job(job: EtlJob) -> dict:
    try:
        result = run_range(job.window_start, job.window_end, operation=job.operation,
                           server_code=job.server_code, force=job.force,
                           task_no=job.task_no, window_minutes=job.window_minutes,
                           sleep_seconds=job.sleep_seconds, stop_on_error=job.stop_on_error,
                           source_mode=job.source_mode,
                           progress_callback=lambda value: _progress(job.job_id, value))
        status = result["status"]
        with SessionLocal.begin() as db:
            db.execute(text(
                "UPDATE t_etl_manual_job SET status=:status,finished_at=NOW(3),result_json=:result "
                "WHERE job_id=:id"
            ), {"status": status, "result": json.dumps(result, ensure_ascii=False, default=str),
                "id": job.job_id})
        return result
    except Exception as error:
        with SessionLocal.begin() as db:
            db.execute(text(
                "UPDATE t_etl_manual_job SET status='FAILED',finished_at=NOW(3),error_message=:error "
                "WHERE job_id=:id"
            ), {"error": str(error)[:2000], "id": job.job_id})
        return {"status": "FAILED", "error": str(error)}


def run_worker(*, once: bool = False, poll_seconds: int | None = None,
               max_jobs: int | None = None) -> dict:
    poll_seconds = poll_seconds or settings.manual_job_poll_seconds
    recovered = recover_running_jobs()
    processed = 0
    while max_jobs is None or processed < max_jobs:
        job = claim_next_job()
        if not job:
            if once:
                break
            time.sleep(poll_seconds)
            continue
        execute_job(job)
        processed += 1
        if once:
            break
    return {"status": "IDLE" if not processed else "SUCCESS",
            "processed_count": processed, "recovered_count": recovered}
