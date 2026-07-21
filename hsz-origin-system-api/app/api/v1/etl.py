from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.etl.job_queue import enqueue_manual_sync, get_manual_job
from app.etl.orchestrator import iter_windows

router = APIRouter(prefix="/etl", tags=["etl"])


class ManualSyncRequest(BaseModel):
    start: datetime
    end: datetime
    rebuild_facts: bool = False
    window_minutes: int = Field(default=120, ge=10, le=1440)
    sleep_seconds: int = Field(default=2, ge=0, le=60)
    resume: bool = True
    continue_on_error: bool = True
    server_code: str | None = None


def two_hour_windows(start: datetime, end: datetime):
    yield from iter_windows(start, end, 120)


def missing_windows(
    start: datetime, end: datetime, successful_batches: list[tuple[datetime, datetime]]
) -> list[dict]:
    """返回未被任一成功批次完整覆盖的两小时同步窗口。"""
    return [
        {"start": window_start, "end": window_end}
        for window_start, window_end in two_hour_windows(start, end)
        if not any(
            batch_start <= window_start and batch_end >= window_end
            for batch_start, batch_end in successful_batches
        )
    ]


def _validate_manual_range(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    if end > datetime.now(end.tzinfo):
        raise HTTPException(status_code=422, detail="结束时间不能晚于当前时间")


def _enqueue(db: Session, payload: ManualSyncRequest) -> dict:
    _validate_manual_range(payload.start, payload.end)
    job = enqueue_manual_sync(
        db,
        start=payload.start,
        end=payload.end,
        window_minutes=payload.window_minutes,
        sleep_seconds=payload.sleep_seconds,
        resume=payload.resume,
        continue_on_error=payload.continue_on_error,
        rebuild_facts=payload.rebuild_facts,
        server_code=payload.server_code,
    )
    db.commit()
    job["status_url"] = f"/api/v1/etl/manual-sync-jobs/{job['job_id']}"
    return job


@router.get("/batches")
def batches(
    page: int = 1,
    page_size: int = 20,
    start: datetime | None = None,
    end: datetime | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="分页参数无效")
    if (start is None) != (end is None) or (start and end and start >= end):
        raise HTTPException(status_code=422, detail="日期区间无效")
    filters = ""
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if status:
        filters = " WHERE status=:status"
        params["status"] = status
    if start and end:
        filters += (
            " AND" if filters else " WHERE"
        ) + " window_start < :end AND window_end > :start"
        params.update({"start": start, "end": end})
    total = db.execute(text(f"SELECT COUNT(*) FROM t_etl_batch{filters}"), params).scalar_one()
    rows = db.execute(
        text(
            "SELECT batch_id,batch_no,job_code,job_type,status,window_start,window_end,"
            "started_at,finished_at,source_row_count,success_event_count,"
            "matched_event_count,error_count,error_summary FROM t_etl_batch"
            + filters
            + " ORDER BY batch_id DESC LIMIT :limit OFFSET :offset"
        ),
        params,
    ).mappings()
    items = [dict(row) for row in rows]
    if items:
        source_rows = db.execute(
            text(
                "SELECT s.batch_id,s.source_server_id,s.status,s.started_at,s.finished_at,"
                "s.source_row_count,s.success_event_count,s.matched_event_count,s.error_count,"
                "s.error_summary,server.server_code FROM t_etl_batch_source s "
                "JOIN t_source_server server "
                "ON server.source_server_id=s.source_server_id WHERE s.batch_id IN ("
                + ",".join(f":batch_{index}" for index in range(len(items)))
                + ") ORDER BY s.batch_source_id"
            ),
            {f"batch_{index}": item["batch_id"] for index, item in enumerate(items)},
        ).mappings()
        by_batch = {item["batch_id"]: [] for item in items}
        for source in source_rows:
            by_batch[source["batch_id"]].append(dict(source))
        for item in items:
            item["sources"] = by_batch[item["batch_id"]]
    summary = None
    if start and end:
        status_rows = db.execute(
            text("SELECT status,window_start,window_end FROM t_etl_batch" + filters), params
        ).mappings()
        status_items = list(status_rows)
        successful = [
            (row["window_start"], row["window_end"])
            for row in status_items
            if row["status"] == "SUCCESS"
        ]
        summary = {
            "success_count": sum(row["status"] == "SUCCESS" for row in status_items),
            "failed_count": sum(row["status"] == "FAILED" for row in status_items),
            "running_count": sum(row["status"] == "RUNNING" for row in status_items),
            "missing_windows": missing_windows(start, end, successful),
        }
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
        "summary": summary,
    }


@router.post(
    "/batches/{batch_id}/sources/{source_server_id}/retry",
    status_code=http_status.HTTP_202_ACCEPTED,
)
def retry_source(batch_id: int, source_server_id: int, db: Session = Depends(get_db)) -> dict:
    source = (
        db.execute(
            text(
                "SELECT b.window_start,b.window_end,s.status,server.server_code "
                "FROM t_etl_batch b JOIN t_etl_batch_source s ON s.batch_id=b.batch_id "
                "JOIN t_source_server server "
                "ON server.source_server_id=s.source_server_id "
                "WHERE b.batch_id=:batch AND s.source_server_id=:source"
            ),
            {"batch": batch_id, "source": source_server_id},
        )
        .mappings()
        .one_or_none()
    )
    if not source or source["status"] != "FAILED":
        raise HTTPException(status_code=422, detail="仅可补同步失败的源服务器记录")
    return _enqueue(
        db,
        ManualSyncRequest(
            start=source["window_start"],
            end=source["window_end"],
            server_code=source["server_code"],
            rebuild_facts=True,
        ),
    )


@router.post("/manual-sync", status_code=http_status.HTTP_202_ACCEPTED)
def manual_sync(payload: ManualSyncRequest, db: Session = Depends(get_db)) -> dict:
    """只写入中心库任务队列，实际同步由独立 worker 执行。"""
    return _enqueue(db, payload)


@router.get("/manual-sync-jobs/{job_id}")
def manual_sync_job(job_id: int, db: Session = Depends(get_db)) -> dict:
    job = get_manual_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="手动同步任务不存在")
    return job
