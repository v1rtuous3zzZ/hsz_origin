import os
import socket
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def start_batch(db: Session, job_code: str, job_type: str, start, end) -> tuple[int, str]:
    number = f"{job_code}-{uuid.uuid4().hex[:12]}"
    result = db.execute(
        text(
            "INSERT INTO t_etl_batch (batch_no, job_code, job_type, window_start, window_end, host_name, process_id) VALUES (:number,:job,:kind,:start,:end,:host,:pid)"
        ),
        {
            "number": number,
            "job": job_code,
            "kind": job_type,
            "start": start,
            "end": end,
            "host": socket.gethostname(),
            "pid": os.getpid(),
        },
    )
    return result.lastrowid, number


def finish_batch(db: Session, batch_id: int, status: str, metrics: dict, error: str | None = None):
    metrics = {
        "source_row_count": 0,
        "success_event_count": 0,
        "matched_event_count": 0,
        "error_count": 0,
        **metrics,
    }
    db.execute(
        text(
            "UPDATE t_etl_batch SET status=:status, finished_at=NOW(3), source_row_count=:source_row_count, success_event_count=:success_event_count, matched_event_count=:matched_event_count, error_count=:error_count, error_summary=:error WHERE batch_id=:id"
        ),
        {"id": batch_id, "status": status, "error": error, **metrics},
    )
