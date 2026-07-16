from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.etl.formal_sync import sync_window

router = APIRouter(prefix="/etl", tags=["etl"])


class ManualSyncRequest(BaseModel):
    start: datetime
    end: datetime


def two_hour_windows(start: datetime, end: datetime):
    current = start
    while current < end:
        next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        current_end = min(current + timedelta(hours=2), next_month, end)
        yield current, current_end
        current = current_end


@router.get("/batches")
def batches(page: int = 1, page_size: int = 20, db: Session = Depends(get_db)) -> dict:
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="分页参数无效")
    total = db.execute(text("SELECT COUNT(*) FROM t_etl_batch")).scalar_one()
    rows = db.execute(text("SELECT batch_id,batch_no,job_code,job_type,status,window_start,window_end,started_at,finished_at,source_row_count,success_event_count,matched_event_count,error_count,error_summary FROM t_etl_batch ORDER BY batch_id DESC LIMIT :limit OFFSET :offset"), {"limit": page_size, "offset": (page - 1) * page_size}).mappings()
    return {"page": page, "page_size": page_size, "total": total, "items": [dict(row) for row in rows]}


@router.post("/manual-sync")
def manual_sync(payload: ManualSyncRequest) -> dict:
    if payload.start >= payload.end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    results = [sync_window(start, end) for start, end in two_hour_windows(payload.start, payload.end)]
    return {"window_count": len(results), "batches": results}
