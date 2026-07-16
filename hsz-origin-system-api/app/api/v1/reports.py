from datetime import datetime, timedelta
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db

router = APIRouter(prefix="/reports", tags=["reports"])


class Granularity(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


def _period(granularity: Granularity, fact_name: str) -> tuple[str, str, str]:
    if granularity == Granularity.HOUR:
        return f"t_fact_{fact_name}_hourly", "stat_hour", "f.stat_hour"
    if granularity == Granularity.MONTH:
        return f"t_fact_{fact_name}_monthly", "stat_month", "f.stat_month"
    if granularity == Granularity.WEEK:
        return f"t_fact_{fact_name}_daily", "stat_date", "DATE_SUB(f.stat_date, INTERVAL WEEKDAY(f.stat_date) DAY)"
    if granularity == Granularity.YEAR:
        return f"t_fact_{fact_name}_daily", "stat_date", "YEAR(f.stat_date)"
    return f"t_fact_{fact_name}_daily", "stat_date", "f.stat_date"


def _time_filter(granularity: Granularity, key: str, start: datetime, end: datetime) -> tuple[str, dict]:
    if granularity == Granularity.HOUR:
        return f"f.{key} >= :start AND f.{key} < :end", {"start": start, "end": end}
    if granularity == Granularity.MONTH:
        start_month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
        last = end - timedelta(microseconds=1)
        end_month = last.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
        return f"f.{key} >= :start AND f.{key} <= :end", {"start": start_month, "end": end_month}
    return f"f.{key} >= :start AND f.{key} <= :end", {
        "start": start.date(),
        "end": (end - timedelta(microseconds=1)).date(),
    }


def _direction_filter(direction: str) -> str:
    return (
        "o.object_name LIKE '%进入本路段'"
        if direction == "entry"
        else "o.object_name LIKE 'G50%驶出本路段'"
    )


@router.get("/directions")
def directions(flow: str = Query(pattern="^(entry|exit)$"), db: Session = Depends(get_db)) -> dict:
    return {"items": _directions(db, flow)}


def _directions(db: Session, flow: str) -> list[dict]:
    direction_where = "object_name LIKE '%进入本路段'" if flow == "entry" else "object_name LIKE '%驶出本路段'"
    availability = "'AVAILABLE'" if flow == "entry" else "CASE WHEN object_name LIKE 'G50%' THEN 'AVAILABLE' ELSE 'UNAVAILABLE' END"
    rows = db.execute(
        text(
            f"SELECT object_no AS direction_id, object_name AS direction_name, {availability} AS availability "
            f"FROM t_stat_object WHERE enabled = 1 AND {direction_where} ORDER BY object_no"
        )
    ).mappings()
    return [dict(row) for row in rows]


@router.get("/options")
def report_options(db: Session = Depends(get_db)) -> dict:
    return {
        "entry_directions": _directions(db, "entry"),
        "exit_directions": _directions(db, "exit"),
        "time_granularities": [item.value for item in Granularity],
    }


def _page(db: Session, grouped: str, parameters: dict, page: int, page_size: int, order_by: str) -> dict:
    total = db.execute(text(f"SELECT COUNT(*) FROM ({grouped}) result"), parameters).scalar_one()
    query_parameters = {**parameters, "offset": (page - 1) * page_size, "limit": page_size}
    rows = db.execute(
        text(f"{grouped} ORDER BY {order_by} LIMIT :limit OFFSET :offset"), query_parameters
    ).mappings()
    return {"page": page, "page_size": page_size, "total": total, "items": [dict(row) for row in rows]}


def _flow_report(
    direction: str,
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int],
    page: int,
    page_size: int,
    db: Session,
) -> dict:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")

    table, key, period = _period(granularity, "flow")
    time_where, parameters = _time_filter(granularity, key, start, end)
    direction_where = _direction_filter(direction)
    if direction_ids:
        placeholders = []
        for index, direction_id in enumerate(direction_ids):
            name = f"direction_id_{index}"
            placeholders.append(f":{name}")
            parameters[name] = direction_id
        direction_where += f" AND o.object_no IN ({','.join(placeholders)})"

    grouped = f"""
        SELECT {period} AS period, o.object_no AS direction_id, o.object_name AS direction_name,
               SUM(f.event_count) AS event_count
        FROM {table} f
        JOIN t_stat_object o ON o.object_no = f.object_no
        WHERE {time_where} AND {direction_where}
        GROUP BY {period}, o.object_no, o.object_name
    """
    return _page(db, grouped, parameters, page, page_size, "period, direction_id")


@router.get("/entry-flow")
def entry_flow(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return _flow_report("entry", start, end, granularity, direction_ids, page, page_size, db)


@router.get("/exit-flow")
def exit_flow(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return _flow_report("exit", start, end, granularity, direction_ids, page, page_size, db)


def _dimension_report(
    fact_name: str,
    dimension_columns: str,
    dimension_group: str,
    dimension_join: str,
    direction: str,
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int],
    page: int,
    page_size: int,
    db: Session,
) -> dict:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    table, key, period = _period(granularity, fact_name)
    time_where, parameters = _time_filter(granularity, key, start, end)
    parameters["unknown_station_name"] = "\u672a\u77e5"
    direction_where = _direction_filter(direction)
    if direction_ids:
        placeholders = []
        for index, direction_id in enumerate(direction_ids):
            name = f"direction_id_{index}"
            placeholders.append(f":{name}")
            parameters[name] = direction_id
        direction_where += f" AND o.object_no IN ({','.join(placeholders)})"
    grouped = f"""
        SELECT {period} AS period, o.object_no AS direction_id, o.object_name AS direction_name,
               {dimension_columns}, SUM(f.event_count) AS event_count
        FROM {table} f
        JOIN t_stat_object o ON o.object_no = f.object_no
        {dimension_join}
        WHERE {time_where} AND {direction_where}
        GROUP BY {period}, o.object_no, o.object_name, {dimension_group}
    """
    return _page(db, grouped, parameters, page, page_size, "period, direction_id, event_count DESC")


def _match_tables(db: Session, start: datetime, end: datetime) -> list[str]:
    month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (end - timedelta(microseconds=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    names = []
    while month <= last_month:
        names.append(f"t_event_object_match_{month:%Y%m}")
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    existing = db.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name IN ("
            + ",".join(f":table_{index}" for index in range(len(names)))
            + ")"
        ),
        {f"table_{index}": name for index, name in enumerate(names)},
    ).scalars()
    return list(existing)


def _entry_station_report(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int],
    page: int,
    page_size: int,
    db: Session,
) -> dict:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    tables = _match_tables(db, start, end)
    if not tables:
        return {"page": page, "page_size": page_size, "total": 0, "items": []}
    period = {
        Granularity.HOUR: "DATE_FORMAT(m.event_time, '%Y-%m-%d %H:00:00')",
        Granularity.DAY: "DATE(m.event_time)",
        Granularity.WEEK: "DATE_SUB(DATE(m.event_time), INTERVAL WEEKDAY(m.event_time) DAY)",
        Granularity.MONTH: "DATE_FORMAT(m.event_time, '%Y-%m-01')",
        Granularity.YEAR: "YEAR(m.event_time)",
    }[granularity]
    parameters = {"start": start, "end": end, "unknown_station_name": "\u672a\u77e5"}
    direction_where = _direction_filter("entry")
    if direction_ids:
        placeholders = []
        for index, direction_id in enumerate(direction_ids):
            name = f"direction_id_{index}"
            placeholders.append(f":{name}")
            parameters[name] = direction_id
        direction_where += f" AND o.object_no IN ({','.join(placeholders)})"
    events = " UNION ALL ".join(
        f"SELECT event_time, object_no, entry_station_code FROM `{table}`" for table in tables
    )
    grouped = f"""
        SELECT {period} AS period, o.object_no AS direction_id, o.object_name AS direction_name,
               m.entry_station_code AS station_code,
               COALESCE(s.station_name, :unknown_station_name) AS station_name,
               COUNT(*) AS event_count
        FROM ({events}) m
        JOIN t_stat_object o ON o.object_no = m.object_no
        LEFT JOIN t_toll_station s ON s.station_code = m.entry_station_code
        WHERE m.event_time >= :start AND m.event_time < :end AND {direction_where}
        GROUP BY {period}, o.object_no, o.object_name, m.entry_station_code,
                 COALESCE(s.station_name, :unknown_station_name)
    """
    return _page(db, grouped, parameters, page, page_size, "period, direction_id, event_count DESC")


@router.get("/vehicle-types")
def vehicle_types(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return _dimension_report(
        "vehicle_type", "f.vehicle_type_code", "f.vehicle_type_code", "", "entry", start, end, granularity,
        direction_ids, page, page_size, db,
    )


@router.get("/entry-stations")
def entry_stations(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return _entry_station_report(start, end, granularity, direction_ids, page, page_size, db)
