from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.etl.job_queue import enqueue_job, get_job
from app.etl.task_runner import validate_backfill_range

router = APIRouter(prefix="/etl", tags=["etl"])


class JobRequest(BaseModel):
    start: datetime
    end: datetime
    server_code: str | None = None
    force: bool = False


def _validate_range(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")


@router.get("/sync-logs")
def sync_logs(page: int = 1, page_size: int = 50, operation: str | None = None,
              status: str | None = None, server_code: str | None = None,
              start: datetime | None = None, end: datetime | None = None,
              db: Session = Depends(get_db)) -> dict:
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="分页参数无效")
    clauses, params = [], {"limit": page_size, "offset": (page - 1) * page_size}
    for field, value in (("operation", operation), ("status", status),
                         ("server_code", server_code)):
        if value:
            clauses.append(f"{field}=:{field}")
            params[field] = value
    if start and end:
        _validate_range(start, end)
        clauses.append("window_start < :end AND window_end > :start")
        params.update({"start": start, "end": end})
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    total = db.execute(text("SELECT COUNT(*) FROM t_etl_sync_log" + where), params).scalar_one()
    rows = db.execute(text(
        "SELECT sync_id,task_no,operation,server_code,window_start,window_end,source_table,"
        "status,check_status,source_unique_count,center_matched_count,missing_count,"
        "duplicate_count,inserted_count,updated_count,query_duration_ms,write_duration_ms,"
        "verify_duration_ms,total_duration_ms,missing_sample_json,error_type,error_message,"
        "started_at,finished_at FROM t_etl_sync_log" + where +
        " ORDER BY sync_log_id DESC LIMIT :limit OFFSET :offset"
    ), params).mappings()
    return {"page": page, "page_size": page_size, "total": total,
            "items": [dict(row) for row in rows]}


@router.get("/missing-windows")
def missing_windows(db: Session = Depends(get_db)) -> dict:
    return {"items": query_missing_windows(db)}


def query_missing_windows(db: Session) -> list[dict]:
    rows = db.execute(text("""
        WITH ranked AS (
            SELECT sync_id,server_code,window_start,window_end,source_unique_count,
                   center_matched_count,missing_count,check_status,
                   ROW_NUMBER() OVER (
                       PARTITION BY server_code,window_start,window_end
                       ORDER BY sync_log_id DESC
                   ) AS row_no
            FROM t_etl_sync_log
            WHERE status IN ('SUCCESS','SKIPPED')
        )
        SELECT server_code,window_start,window_end,sync_id AS latest_sync_id,
               source_unique_count,center_matched_count,missing_count,check_status
        FROM ranked WHERE row_no=1 AND check_status='MISSING'
        ORDER BY window_start DESC,server_code
    """)).mappings()
    return [dict(row) for row in rows]


def _enqueue(db: Session, operation: str, payload: JobRequest) -> dict:
    _validate_range(payload.start, payload.end)
    if operation == "BACKFILL":
        try:
            validate_backfill_range(payload.start, payload.end)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    result = enqueue_job(db, operation=operation, start=payload.start, end=payload.end,
                         server_code=payload.server_code, force=payload.force)
    db.commit()
    return result


@router.post("/jobs/backfill", status_code=http_status.HTTP_202_ACCEPTED)
def create_backfill(payload: JobRequest, db: Session = Depends(get_db)) -> dict:
    return _enqueue(db, "BACKFILL", payload)


@router.post("/jobs/check", status_code=http_status.HTTP_202_ACCEPTED)
def create_check(payload: JobRequest, db: Session = Depends(get_db)) -> dict:
    return _enqueue(db, "CHECK", payload)


@router.post("/sync-logs/{sync_id}/repair", status_code=http_status.HTTP_202_ACCEPTED)
def create_repair(sync_id: str, db: Session = Depends(get_db)) -> dict:
    row = db.execute(text(
        "SELECT server_code,window_start,window_end FROM t_etl_sync_log WHERE sync_id=:id"
    ), {"id": sync_id}).mappings().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="同步日志不存在")
    result = enqueue_job(db, operation="REPAIR", start=row["window_start"], end=row["window_end"],
                         server_code=row["server_code"], force=True)
    db.commit()
    return result


@router.get("/jobs/{job_id}")
def job_status(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ETL 任务不存在")
    return job
