from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ROUTES = ("G50", "G1521", "G1522", "S17")
VEHICLE_GROUPS = (
    ("客车1-3", "CAST(f.vehicle_type_code AS UNSIGNED) BETWEEN 1 AND 3"),
    ("客车其他", "CAST(f.vehicle_type_code AS UNSIGNED) BETWEEN 4 AND 9"),
    ("货车1-4", "CAST(f.vehicle_type_code AS UNSIGNED) BETWEEN 10 AND 13"),
    (
        "货车其他",
        "CAST(f.vehicle_type_code AS UNSIGNED) BETWEEN 14 AND 19 OR f.vehicle_type_code IS NULL OR f.vehicle_type_code IN ('', 'UNKNOWN') OR CAST(f.vehicle_type_code AS UNSIGNED) <= 0",
    ),
    ("专项作业车", "CAST(f.vehicle_type_code AS UNSIGNED) >= 20"),
)


@router.get("/latest-range")
def latest_range(db: Session = Depends(get_db)) -> dict:
    latest = db.execute(text("SELECT MAX(stat_hour) FROM t_fact_flow_hourly")).scalar_one()
    if latest is None:
        return {"start": None, "end": None, "latest_hour": None}
    start = latest.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return {"start": start, "end": end, "latest_hour": latest}


def _validate_range(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")


def _hours(start: datetime, end: datetime) -> list[datetime]:
    current = start.replace(minute=0, second=0, microsecond=0)
    last = (end - timedelta(microseconds=1)).replace(minute=0, second=0, microsecond=0)
    result = []
    while current <= last:
        result.append(current)
        current += timedelta(hours=1)
    return result


def _hour_labels(start: datetime, end: datetime) -> list[str]:
    return [item.strftime("%H:00") for item in _hours(start, end)]


def _hour_map(rows: list[dict], start: datetime, end: datetime) -> dict[tuple, list[int]]:
    hours = _hours(start, end)
    index = {item.strftime("%Y-%m-%d %H:00:00"): pos for pos, item in enumerate(hours)}
    result: dict[tuple, list[int]] = {}
    for row in rows:
        key = row["group_key"]
        values = result.setdefault(key, [0] * len(hours))
        period = str(row["stat_hour"])
        if period in index:
            values[index[period]] = int(row["event_count"] or 0)
    return result


@router.get("/route-stack")
def route_stack(start: datetime, end: datetime, db: Session = Depends(get_db)) -> dict:
    _validate_range(start, end)
    rows = (
        db.execute(
            text(
                "SELECT DATE_FORMAT(f.stat_hour, '%Y-%m-%d %H:00:00') AS stat_hour, "
                "CONCAT(o.route_code, '|', o.direction_name) AS group_key, "
                "o.route_code, o.direction_name, SUM(f.event_count) AS event_count "
                "FROM t_fact_flow_hourly f "
                "JOIN t_stat_object o ON o.object_no=f.object_no "
                "WHERE f.stat_hour>=:start AND f.stat_hour<:end AND o.enabled=1 AND o.flow_type='ENTRY' "
                "GROUP BY f.stat_hour, o.route_code, o.direction_name "
                "ORDER BY f.stat_hour, o.route_code, o.direction_name"
            ),
            {"start": start, "end": end},
        )
        .mappings()
        .all()
    )
    grouped = _hour_map([dict(row) for row in rows], start, end)
    series = []
    for route in ROUTES:
        route_rows = [dict(row) for row in rows if row["route_code"] == route]
        directions = sorted({row["direction_name"] or "未知方向" for row in route_rows})
        for direction in directions:
            series.append(
                {
                    "name": f"{route}-{direction}",
                    "stack": route,
                    "data": grouped.get(f"{route}|{direction}", [0] * len(_hours(start, end))),
                }
            )
    local = (
        db.execute(
            text(
                "SELECT DATE_FORMAT(stat_hour, '%Y-%m-%d %H:00:00') AS stat_hour, "
                "'local' AS group_key, SUM(event_count) AS event_count "
                "FROM t_fact_local_entry_flow_hourly "
                "WHERE stat_hour>=:start AND stat_hour<:end GROUP BY stat_hour"
            ),
            {"start": start, "end": end},
        )
        .mappings()
        .all()
    )
    local_map = _hour_map([dict(row) for row in local], start, end)
    series.insert(
        0, {"name": "本路段", "data": local_map.get("local", [0] * len(_hours(start, end)))}
    )
    return {"times": _hour_labels(start, end), "series": series}


@router.get("/direction-flow")
def direction_flow(start: datetime, end: datetime, db: Session = Depends(get_db)) -> dict:
    _validate_range(start, end)
    rows = (
        db.execute(
            text(
                "SELECT DATE_FORMAT(f.stat_hour, '%Y-%m-%d %H:00:00') AS stat_hour, "
                "CONCAT(o.route_code, '|', o.direction_name) AS group_key, "
                "o.route_code, o.direction_name, SUM(f.event_count) AS event_count "
                "FROM t_fact_flow_hourly f "
                "JOIN t_stat_object o ON o.object_no=f.object_no "
                "WHERE f.stat_hour>=:start AND f.stat_hour<:end AND o.enabled=1 AND o.flow_type='ENTRY' "
                "GROUP BY f.stat_hour, o.route_code, o.direction_name "
                "ORDER BY f.stat_hour, o.route_code, o.direction_name"
            ),
            {"start": start, "end": end},
        )
        .mappings()
        .all()
    )
    row_dicts = [dict(row) for row in rows]
    grouped = _hour_map(row_dicts, start, end)
    size = len(_hours(start, end))
    routes = []
    for route in ROUTES:
        directions = sorted(
            {row["direction_name"] or "未知方向" for row in row_dicts if row["route_code"] == route}
        )
        routes.append(
            {
                "key": route,
                "label": route,
                "directionALabel": directions[0] if directions else "",
                "directionBLabel": directions[1] if len(directions) > 1 else "",
                "directionACounts": grouped.get(f"{route}|{directions[0]}", [0] * size)
                if directions
                else [0] * size,
                "directionBCounts": grouped.get(f"{route}|{directions[1]}", [0] * size)
                if len(directions) > 1
                else [0] * size,
            }
        )
    return {"times": _hour_labels(start, end), "routes": routes}


@router.get("/local-station-flow")
def local_station_flow(
    start: datetime,
    end: datetime,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    _validate_range(start, end)
    rows = (
        db.execute(
            text(
                "SELECT DATE_FORMAT(f.stat_hour, '%Y-%m-%d %H:00:00') AS stat_hour, "
                "s.station_name AS group_key, s.station_name, SUM(f.event_count) AS event_count "
                "FROM t_fact_local_entry_station_flow_hourly f "
                "JOIN t_toll_station s ON s.toll_station_id=f.toll_station_id "
                "WHERE f.stat_hour>=:start AND f.stat_hour<:end "
                "GROUP BY f.stat_hour, s.station_name ORDER BY f.stat_hour, s.station_name"
            ),
            {"start": start, "end": end},
        )
        .mappings()
        .all()
    )
    row_dicts = [dict(row) for row in rows]
    grouped = _hour_map(row_dicts, start, end)
    totals = {}
    for row in row_dicts:
        totals[row["station_name"]] = totals.get(row["station_name"], 0) + int(
            row["event_count"] or 0
        )
    names = [
        name for name, _ in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]
    return {
        "times": _hour_labels(start, end),
        "series": [{"name": name, "counts": grouped.get(name, [])} for name in names],
    }


@router.get("/section-rank")
def section_rank(
    start: datetime,
    end: datetime,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict:
    _validate_range(start, end)
    month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (end - timedelta(microseconds=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    tables = []
    while month <= last_month:
        tables.append(f"t_ods_event_{month:%Y%m}")
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    existing = (
        db.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ("
                + ",".join(f":table_{index}" for index in range(len(tables)))
                + ")"
            ),
            {f"table_{index}": name for index, name in enumerate(tables)},
        )
        .scalars()
        .all()
    )
    if not existing:
        return {"totalCount": 0, "items": []}
    union_sql = " UNION ALL ".join(
        f"SELECT event_time,current_physical_gantry_code,success_flag FROM `{table}`"
        for table in existing
    )
    rows = (
        db.execute(
            text(
                "SELECT COALESCE(p.gantry_name, src.current_physical_gantry_code) AS name, COUNT(*) AS count "
                f"FROM ({union_sql}) src "
                "JOIN t_physical_gantry p ON p.physical_gantry_code=src.current_physical_gantry_code "
                "WHERE src.event_time>=:start AND src.event_time<:end AND src.success_flag=1 "
                "AND p.enabled=1 AND p.collection_enabled=1 "
                "GROUP BY src.current_physical_gantry_code, p.gantry_name "
                "ORDER BY count DESC, name LIMIT :limit"
            ),
            {"start": start, "end": end, "limit": limit},
        )
        .mappings()
        .all()
    )
    items = [{"name": row["name"], "count": int(row["count"] or 0)} for row in rows]
    return {"totalCount": sum(item["count"] for item in items), "items": items}


@router.get("/vehicle-type-ratio")
def vehicle_type_ratio(start: datetime, end: datetime, db: Session = Depends(get_db)) -> dict:
    _validate_range(start, end)
    items = []
    for name, condition in VEHICLE_GROUPS:
        count = db.execute(
            text(
                "SELECT COALESCE(SUM(f.event_count),0) FROM t_fact_vehicle_type_hourly f "
                "JOIN t_stat_object o ON o.object_no=f.object_no "
                f"WHERE f.stat_hour>=:start AND f.stat_hour<:end AND o.enabled=1 AND o.flow_type='ENTRY' AND ({condition})"
            ),
            {"start": start, "end": end},
        ).scalar_one()
        items.append({"name": name, "count": int(count or 0)})
    return {"items": items}


def _province_counts(db: Session, start: datetime, end: datetime) -> dict[str, int]:
    month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (end - timedelta(microseconds=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    tables = []
    while month <= last_month:
        tables.append(f"t_event_object_match_{month:%Y%m}")
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    existing = (
        db.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ("
                + ",".join(f":table_{index}" for index in range(len(tables)))
                + ")"
            ),
            {f"table_{index}": name for index, name in enumerate(tables)},
        )
        .scalars()
        .all()
    )
    if not existing:
        return {}
    events = " UNION ALL ".join(
        f"SELECT event_time,entry_station_code,event_key FROM `{table}`" for table in existing
    )
    rows = (
        db.execute(
            text(
                "SELECT COALESCE(s.province_code,'UNKNOWN') AS province_id, COUNT(DISTINCT m.event_key) AS total "
                f"FROM ({events}) m LEFT JOIN t_toll_station s ON s.station_code=m.entry_station_code "
                "WHERE m.event_time>=:start AND m.event_time<:end "
                "GROUP BY COALESCE(s.province_code,'UNKNOWN')"
            ),
            {"start": start, "end": end},
        )
        .mappings()
        .all()
    )
    return {str(row["province_id"]): int(row["total"] or 0) for row in rows}


@router.get("/province-summary")
def province_summary(
    start: datetime,
    end: datetime,
    compare_start: datetime,
    compare_end: datetime,
    week_start: datetime,
    week_end: datetime,
    db: Session = Depends(get_db),
) -> dict:
    _validate_range(start, end)
    current = _province_counts(db, start, end)
    compare = _province_counts(db, compare_start, compare_end)
    week = _province_counts(db, week_start, week_end)
    items = [
        {
            "provinceId": province,
            "count": count,
            "compareCount": compare.get(province),
            "weekCount": week.get(province),
        }
        for province, count in sorted(current.items(), key=lambda item: item[1], reverse=True)
    ]
    return {"items": items}
