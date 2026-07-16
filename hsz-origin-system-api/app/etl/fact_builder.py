from sqlalchemy import text
from sqlalchemy.orm import Session


def rebuild(db: Session, start, end) -> int:
    # Rebuild is deliberately centralized: callers invoke it only after every source succeeds.
    months = {f"{point:%Y%m}" for point in (start, end)}
    for month in months:
        matches = f"t_event_object_match_{month}"
        db.execute(
            text("DELETE FROM t_fact_flow_hourly WHERE stat_hour>=:start AND stat_hour<:end"),
            {"start": start, "end": end},
        )
        db.execute(
            text(
                f'INSERT INTO t_fact_flow_hourly (object_no,stat_hour,event_count,updated_at) SELECT object_no, DATE_FORMAT(event_time, "%Y-%m-%d %H:00:00"), COUNT(*), NOW(3) FROM `{matches}` WHERE event_time>=:start AND event_time<:end GROUP BY object_no, DATE_FORMAT(event_time, "%Y-%m-%d %H:00:00")'
            ),
            {"start": start, "end": end},
        )
    return 0
