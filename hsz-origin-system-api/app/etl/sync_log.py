import json
import uuid

from sqlalchemy import text


def start_sync(db, *, task_no: str, operation: str, server, start, end) -> tuple[int, str]:
    sync_id = str(uuid.uuid4())
    result = db.execute(
        text(
            "INSERT INTO t_etl_sync_log "
            "(sync_id,task_no,operation,source_server_id,server_code,window_start,window_end,status) "
            "VALUES (:sync_id,:task_no,:operation,:source_id,:server_code,:start,:end,'RUNNING')"
        ),
        {"sync_id": sync_id, "task_no": task_no, "operation": operation,
         "source_id": server.source_server_id, "server_code": server.server_code,
         "start": start, "end": end},
    )
    return int(result.lastrowid), sync_id


def latest_complete(db, server_code: str, start, end) -> bool:
    row = db.execute(text(
        "SELECT check_status FROM t_etl_sync_log WHERE server_code=:server "
        "AND window_start=:start AND window_end=:end AND status IN ('SUCCESS','SKIPPED') "
        "ORDER BY sync_log_id DESC LIMIT 1"
    ), {"server": server_code, "start": start, "end": end}).scalar_one_or_none()
    return row == "COMPLETE"


def finish_sync(db, sync_id: str, *, status: str, check_status: str = "UNCHECKED", **values) -> None:
    allowed = {"source_table", "source_unique_count", "center_matched_count", "missing_count",
               "duplicate_count", "inserted_count", "updated_count", "query_duration_ms",
               "write_duration_ms", "verify_duration_ms", "total_duration_ms", "error_type",
               "error_message"}
    assignments = ["status=:status", "check_status=:check_status", "finished_at=NOW(3)"]
    params = {"sync_id": sync_id, "status": status, "check_status": check_status}
    for key, value in values.items():
        if key in allowed:
            assignments.append(f"{key}=:{key}")
            params[key] = value
    missing = values.get("missing_ids")
    if missing is not None:
        assignments.append("missing_sample_json=:missing_sample_json")
        params["missing_sample_json"] = json.dumps(sorted(missing)[:20], ensure_ascii=False)
    db.execute(text(f"UPDATE t_etl_sync_log SET {','.join(assignments)} WHERE sync_id=:sync_id"), params)
