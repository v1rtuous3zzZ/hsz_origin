from datetime import datetime, timedelta
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.dependencies import get_db

router = APIRouter(prefix="/reports", tags=["reports"])
LOCAL_ENTRY_DIRECTION_ID = 199
LOCAL_ENTRY_DIRECTION_NAME = "本路段收费站来源"


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
        return (
            f"t_fact_{fact_name}_daily",
            "stat_date",
            "DATE_SUB(f.stat_date, INTERVAL WEEKDAY(f.stat_date) DAY)",
        )
    if granularity == Granularity.YEAR:
        return f"t_fact_{fact_name}_daily", "stat_date", "YEAR(f.stat_date)"
    return f"t_fact_{fact_name}_daily", "stat_date", "f.stat_date"


def _time_filter(
    granularity: Granularity, key: str, start: datetime, end: datetime
) -> tuple[str, dict]:
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
        "o.flow_type = 'ENTRY'"
        if direction == "entry"
        else "o.flow_type = 'EXIT' AND o.route_code = 'G50'"
    )


@router.get("/directions")
def directions(flow: str = Query(pattern="^(entry|exit)$"), db: Session = Depends(get_db)) -> dict:
    return {"items": _directions(db, flow)}


def _directions(db: Session, flow: str) -> list[dict]:
    direction_where = "flow_type = 'ENTRY'" if flow == "entry" else "flow_type = 'EXIT'"
    availability = (
        "'AVAILABLE'"
        if flow == "entry"
        else "CASE WHEN route_code = 'G50' THEN 'AVAILABLE' ELSE 'UNAVAILABLE' END"
    )
    rows = db.execute(
        text(
            f"SELECT object_no AS direction_id, object_name AS direction_name, {availability} AS availability "
            f"FROM t_stat_object WHERE enabled = 1 AND {direction_where} ORDER BY sort_no"
        )
    ).mappings()
    items = [dict(row) for row in rows]
    if flow == "entry":
        items.append(
            {
                "direction_id": LOCAL_ENTRY_DIRECTION_ID,
                "direction_name": LOCAL_ENTRY_DIRECTION_NAME,
                "availability": "AVAILABLE",
            }
        )
    return items


@router.get("/options")
def report_options(db: Session = Depends(get_db)) -> dict:
    return {
        "entry_directions": _directions(db, "entry"),
        "exit_directions": _directions(db, "exit"),
        "local_entry_stations": _local_entry_stations(db),
        "vehicle_types": _vehicle_types(db),
        "media_types": [
            {"media_type_code": "1", "media_type_name": "OBU"},
            {"media_type_code": "2", "media_type_name": "CPC"},
            {"media_type_code": "UNKNOWN", "media_type_name": "无介质"},
        ],
        "time_granularities": [item.value for item in Granularity],
    }


def _local_entry_stations(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT s.toll_station_id AS station_id, s.station_name "
            "FROM t_local_entry_station l JOIN t_toll_station s ON s.toll_station_id=l.toll_station_id "
            "WHERE l.enabled=1 ORDER BY l.sort_no, s.station_code"
        )
    ).mappings()
    return [dict(row) for row in rows]


def _vehicle_types(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT vehicle_type_code, vehicle_type_name "
            "FROM t_vehicle_type_dict WHERE enabled=1 "
            "ORDER BY CAST(vehicle_type_code AS UNSIGNED), vehicle_type_code"
        )
    ).mappings()
    return [dict(row) for row in rows]


def _page(
    db: Session, grouped: str, parameters: dict, page: int, page_size: int, order_by: str
) -> dict:
    total = db.execute(text(f"SELECT COUNT(*) FROM ({grouped}) result"), parameters).scalar_one()
    query_parameters = {**parameters, "offset": (page - 1) * page_size, "limit": page_size}
    rows = db.execute(
        text(f"{grouped} ORDER BY {order_by} LIMIT :limit OFFSET :offset"), query_parameters
    ).mappings()
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [dict(row) for row in rows],
    }


def _page_grouped_rows(
    db: Session, grouped: str, parameters: dict, page: int, page_size: int, order_by: str
) -> dict:
    rows = [
        dict(row)
        for row in db.execute(text(f"{grouped} ORDER BY {order_by}"), parameters).mappings()
    ]
    offset = (page - 1) * page_size
    return {
        "page": page,
        "page_size": page_size,
        "total": len(rows),
        "items": rows[offset : offset + page_size],
    }


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
    regular_direction_ids = direction_ids
    if direction == "entry":
        regular_direction_ids = [item for item in direction_ids if item != LOCAL_ENTRY_DIRECTION_ID]
    if regular_direction_ids:
        placeholders = []
        for index, direction_id in enumerate(regular_direction_ids):
            name = f"direction_id_{index}"
            placeholders.append(f":{name}")
            parameters[name] = direction_id
        direction_where += f" AND o.object_no IN ({','.join(placeholders)})"
    elif direction_ids:
        direction_where += " AND 1=0"

    normal_grouped = f"""
        SELECT {period} AS period, o.object_no AS direction_id, o.object_name AS direction_name,
               SUM(f.event_count) AS event_count
        FROM {table} f
        JOIN t_stat_object o ON o.object_no = f.object_no
        WHERE {time_where} AND {direction_where}
        GROUP BY {period}, o.object_no, o.object_name
    """
    if direction != "entry":
        return _page(db, normal_grouped, parameters, page, page_size, "period, direction_id")

    include_local = not direction_ids or LOCAL_ENTRY_DIRECTION_ID in direction_ids
    local_grouped = f"""
        SELECT {period} AS period, {LOCAL_ENTRY_DIRECTION_ID} AS direction_id,
               '{LOCAL_ENTRY_DIRECTION_NAME}' AS direction_name, SUM(f.event_count) AS event_count
        FROM {_period(granularity, "local_entry_flow")[0]} f
        WHERE {time_where}
        GROUP BY {period}
    """
    grouped = normal_grouped if not include_local else f"{normal_grouped} UNION ALL {local_grouped}"
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


@router.get("/local-entry-station-flow")
def local_entry_station_flow(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    station_ids: list[int] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    table, key, period = _period(granularity, "local_entry_station_flow")
    time_where, parameters = _time_filter(granularity, key, start, end)
    station_where = "l.enabled=1"
    if station_ids:
        placeholders = []
        for index, station_id in enumerate(station_ids):
            name = f"station_id_{index}"
            placeholders.append(f":{name}")
            parameters[name] = station_id
        station_where += f" AND f.toll_station_id IN ({','.join(placeholders)})"
    grouped = f"""
        SELECT {period} AS period, s.station_name, l.sort_no AS station_sort_no,
               SUM(f.event_count) AS event_count
        FROM {table} f
        JOIN t_local_entry_station l ON l.toll_station_id=f.toll_station_id
        JOIN t_toll_station s ON s.toll_station_id=f.toll_station_id
        WHERE {time_where} AND {station_where}
        GROUP BY {period}, s.station_name, l.sort_no
    """
    return _page(db, grouped, parameters, page, page_size, "station_sort_no, period")


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


def _monthly_tables(prefix: str, db: Session, start: datetime, end: datetime) -> list[str]:
    month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (end - timedelta(microseconds=1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    names = []
    while month <= last_month:
        names.append(f"{prefix}_{month:%Y%m}")
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


def _entry_dimension_report(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int],
    page: int,
    page_size: int,
    db: Session,
    dimension_select: str,
    dimension_group: str,
    dimension_parameters: dict,
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
    parameters = {"start": start, "end": end, **dimension_parameters}
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
               {dimension_select},
               COUNT(*) AS event_count
        FROM ({events}) m
        JOIN t_stat_object o ON o.object_no = m.object_no
        LEFT JOIN t_toll_station s ON s.station_code = m.entry_station_code
        WHERE m.event_time >= :start AND m.event_time < :end AND {direction_where}
        GROUP BY {period}, o.object_no, o.object_name, {dimension_group}
    """
    return _page(db, grouped, parameters, page, page_size, "period, direction_id, event_count DESC")


@router.get("/media-vehicle-types")
def media_vehicle_types(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int] = Query(default=[]),
    vehicle_type_codes: list[str] = Query(default=[]),
    media_type_codes: list[str] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    if start >= end:
        raise HTTPException(status_code=422, detail="结束时间必须晚于开始时间")
    if len(direction_ids) != 1:
        raise HTTPException(status_code=422, detail="无介质车型统计必须选择一个入口方向")
    match_tables = _match_tables(db, start, end)
    ods_tables = set(_monthly_tables("t_ods_event", db, start, end))
    pairs = []
    for match_table in match_tables:
        suffix = match_table.rsplit("_", 1)[-1]
        ods_table = f"t_ods_event_{suffix}"
        if ods_table in ods_tables:
            pairs.append((match_table, ods_table))
    if not pairs:
        return {"page": page, "page_size": page_size, "total": 0, "items": []}
    period = {
        Granularity.HOUR: "DATE_FORMAT(m.event_time, '%Y-%m-%d %H:00:00')",
        Granularity.DAY: "DATE(m.event_time)",
        Granularity.WEEK: "DATE_SUB(DATE(m.event_time), INTERVAL WEEKDAY(m.event_time) DAY)",
        Granularity.MONTH: "DATE_FORMAT(m.event_time, '%Y-%m-01')",
        Granularity.YEAR: "YEAR(m.event_time)",
    }[granularity]
    parameters = {"start": start, "end": end}
    direction_where = _direction_filter("entry")
    parameters["direction_id"] = direction_ids[0]
    direction_where += " AND o.object_no = :direction_id"
    media_expression = "COALESCE(NULLIF(e.media_type, ''), 'UNKNOWN')"
    if vehicle_type_codes:
        placeholders = []
        for index, code in enumerate(vehicle_type_codes):
            name = f"vehicle_type_code_{index}"
            placeholders.append(f":{name}")
            parameters[name] = code
        direction_where += f" AND e.vehicle_type_code IN ({','.join(placeholders)})"
    if media_type_codes:
        placeholders = []
        for index, code in enumerate(media_type_codes):
            name = f"media_type_code_{index}"
            placeholders.append(f":{name}")
            parameters[name] = code
        direction_where += f" AND {media_expression} IN ({','.join(placeholders)})"
    events = " UNION ALL ".join(
        "SELECT m.event_key,m.event_time,m.object_no,m.vehicle_type_code,ods.media_type "
        f"FROM `{match_table}` m JOIN `{ods_table}` ods ON ods.event_key=m.event_key "
        "WHERE m.event_time >= :start AND m.event_time < :end AND m.object_no = :direction_id "
        "AND ods.event_time >= :start AND ods.event_time < :end"
        for match_table, ods_table in pairs
    )
    media_label = (
        "CASE WHEN e.media_type='1' THEN 'OBU' WHEN e.media_type='2' THEN 'CPC' ELSE '无介质' END"
    )
    grouped = f"""
        SELECT {period.replace("m.", "e.")} AS period,
               o.object_no AS direction_id, o.object_name AS direction_name,
               {media_label} AS media_type_name,
               {media_expression} AS media_type_code,
               e.vehicle_type_code,
               COALESCE(v.vehicle_type_name, '未知车型') AS vehicle_type_name,
               COUNT(*) AS event_count
        FROM ({events}) e
        JOIN t_stat_object o ON o.object_no = e.object_no
        LEFT JOIN t_vehicle_type_dict v ON v.vehicle_type_code = e.vehicle_type_code AND v.enabled = 1
        WHERE e.event_time >= :start AND e.event_time < :end AND {direction_where}
        GROUP BY {period.replace("m.", "e.")}, o.object_no, o.object_name,
                 {media_label}, {media_expression},
                 e.vehicle_type_code, COALESCE(v.vehicle_type_name, '未知车型')
    """
    return _page_grouped_rows(
        db,
        grouped,
        parameters,
        page,
        page_size,
        "period, direction_id, media_type_name, event_count DESC",
    )


def _entry_province_report(
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
    return _entry_dimension_report(
        start,
        end,
        granularity,
        direction_ids,
        page,
        page_size,
        db,
        "COALESCE(s.province_code, :unknown_province_code) AS province_code",
        "COALESCE(s.province_code, :unknown_province_code)",
        {"unknown_province_code": "UNKNOWN"},
    )


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
        "vehicle_type",
        "f.vehicle_type_code, COALESCE(v.vehicle_type_name, '未知车型') AS vehicle_type_name",
        "f.vehicle_type_code, COALESCE(v.vehicle_type_name, '未知车型')",
        "LEFT JOIN t_vehicle_type_dict v ON v.vehicle_type_code = f.vehicle_type_code AND v.enabled = 1",
        "entry",
        start,
        end,
        granularity,
        direction_ids,
        page,
        page_size,
        db,
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
    return _entry_dimension_report(
        start,
        end,
        granularity,
        direction_ids,
        page,
        page_size,
        db,
        "m.entry_station_code AS station_code, COALESCE(s.station_name, :unknown_station_name) AS station_name",
        "m.entry_station_code, COALESCE(s.station_name, :unknown_station_name)",
        {"unknown_station_name": "\u672a\u77e5"},
    )


@router.get("/entry-provinces")
def entry_provinces(
    start: datetime,
    end: datetime,
    granularity: Granularity,
    direction_ids: list[int] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict:
    return _entry_province_report(start, end, granularity, direction_ids, page, page_size, db)
