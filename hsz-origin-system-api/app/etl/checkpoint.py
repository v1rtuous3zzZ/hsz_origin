from sqlalchemy import text
from sqlalchemy.orm import Session


def checkpoint(db: Session, job_code: str, source_server_id: int):
    return db.execute(
        text(
            "SELECT watermark_time FROM t_etl_checkpoint WHERE job_code=:job AND source_server_id=:server"
        ),
        {"job": job_code, "server": source_server_id},
    ).scalar_one_or_none()


def advance(db: Session, job_code: str, source_server_id: int, watermark, batch_id: int):
    db.execute(
        text(
            "INSERT INTO t_etl_checkpoint (job_code, source_server_id, watermark_time, last_success_batch_id, last_success_at) VALUES (:job, :server, :watermark, :batch, NOW(3)) ON DUPLICATE KEY UPDATE watermark_time=VALUES(watermark_time), last_success_batch_id=VALUES(last_success_batch_id), last_success_at=VALUES(last_success_at), last_error_at=NULL, last_error_summary=NULL, version_no=version_no+1"
        ),
        {"job": job_code, "server": source_server_id, "watermark": watermark, "batch": batch_id},
    )
