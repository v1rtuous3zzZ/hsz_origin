"""中心库中的源窗口成功覆盖查询，不访问门架数据库。"""

from datetime import datetime

from sqlalchemy import text

from app.db.session import SessionLocal


def covers_window(
    intervals: list[tuple[datetime, datetime]], start: datetime, end: datetime
) -> bool:
    covered_until = start
    for interval_start, interval_end in intervals:
        if interval_start > covered_until:
            return False
        if interval_end > covered_until:
            covered_until = interval_end
        if covered_until >= end:
            return True
    return False


def successful_server_codes(start: datetime, end: datetime) -> set[str]:
    with SessionLocal() as db:
        rows = db.execute(
            text(
                "SELECT server.server_code,source.actual_start,source.actual_end "
                "FROM t_etl_batch_source source "
                "JOIN t_etl_batch batch ON batch.batch_id=source.batch_id "
                "JOIN t_source_server server "
                "ON server.source_server_id=source.source_server_id "
                "WHERE source.actual_start < :end AND source.actual_end > :start "
                "AND source.status='SUCCESS' "
                "ORDER BY server.server_code,source.actual_start,source.actual_end"
            ),
            {"start": start, "end": end},
        )
        intervals_by_server: dict[str, list[tuple[datetime, datetime]]] = {}
        for server_code, actual_start, actual_end in rows:
            intervals_by_server.setdefault(server_code, []).append(
                (actual_start, actual_end)
            )
        return {
            server_code
            for server_code, intervals in intervals_by_server.items()
            if covers_window(intervals, start, end)
        }
