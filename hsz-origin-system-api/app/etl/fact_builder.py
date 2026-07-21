from datetime import datetime, timedelta

from sqlalchemy import text


def rebuild(db, start: datetime, end: datetime, batch_id: int) -> None:
    """重建受影响事实；小时/日走时间索引，月事实从中心库日事实汇总。"""
    if start.strftime("%Y%m") != (end - timedelta(microseconds=1)).strftime("%Y%m"):
        raise ValueError("事实重算仅接受单月窗口")
    matches = f"t_event_object_match_{start:%Y%m}"
    hour_a = start.replace(minute=0, second=0, microsecond=0)
    hour_b = (end - timedelta(microseconds=1)).replace(
        minute=0, second=0, microsecond=0
    ) + timedelta(hours=1)
    date_a, date_b = start.date(), (end - timedelta(microseconds=1)).date()
    month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
    month_end = (start.replace(day=28) + timedelta(days=4)).replace(day=1).date()
    _flow(db, matches, hour_a, hour_b, date_a, date_b, month, month_end, batch_id)
    _local_entry_flow(db, matches, hour_a, hour_b, date_a, date_b, month, month_end, batch_id)
    _local_entry_station_flow(
        db, matches, hour_a, hour_b, date_a, date_b, month, month_end, batch_id
    )
    _dimension(
        db,
        matches,
        "source_station",
        "toll_station_id",
        "s.toll_station_id",
        "JOIN t_toll_station s ON s.station_code=m.entry_station_code",
        hour_a,
        hour_b,
        date_a,
        date_b,
        month,
        month_end,
        batch_id,
    )
    _dimension(
        db,
        matches,
        "vehicle_type",
        "vehicle_type_code,category_code",
        "COALESCE(m.vehicle_type_code,'UNKNOWN'),COALESCE(v.category_code,'UNKNOWN')",
        "LEFT JOIN t_vehicle_type_dict v ON v.vehicle_type_code=m.vehicle_type_code AND v.enabled=1",
        hour_a,
        hour_b,
        date_a,
        date_b,
        month,
        month_end,
        batch_id,
    )


def _flow(db, m, ha, hb, da, dbb, month, month_end, batch):
    for grain, key, bucket, where, args in (
        (
            "hourly",
            "stat_hour",
            "DATE_FORMAT(event_time,'%Y-%m-%d %H:00:00')",
            "event_time>=:a AND event_time<:b",
            {"a": ha, "b": hb},
        ),
        (
            "daily",
            "stat_date",
            "DATE(event_time)",
            "DATE(event_time)>=:a AND DATE(event_time)<=:b",
            {"a": da, "b": dbb},
        ),
    ):
        table = f"t_fact_flow_{grain}"
        if grain == "hourly":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<:b"), args)
        elif grain == "daily":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<=:b"), args)
        db.execute(
            text(
                f"INSERT INTO {table} (object_no,{key},event_count,last_batch_id) SELECT object_no,{bucket},COUNT(*),:batch FROM `{m}` WHERE {where} GROUP BY object_no,{bucket}"
            ),
            {**args, "batch": batch},
        )
    db.execute(text("DELETE FROM t_fact_flow_monthly WHERE stat_month=:month"), {"month": month})
    db.execute(
        text(
            "INSERT INTO t_fact_flow_monthly (object_no,stat_month,event_count,last_batch_id) SELECT object_no,:month,SUM(event_count),:batch FROM t_fact_flow_daily WHERE stat_date>=:month AND stat_date<:month_end GROUP BY object_no"
        ),
        {"month": month, "month_end": month_end, "batch": batch},
    )


def _local_entry_flow(db, m, ha, hb, da, dbb, month, month_end, batch):
    for grain, key, bucket, where, args in (
        (
            "hourly",
            "stat_hour",
            "DATE_FORMAT(m.event_time,'%Y-%m-%d %H:00:00')",
            "m.event_time>=:a AND m.event_time<:b",
            {"a": ha, "b": hb},
        ),
        (
            "daily",
            "stat_date",
            "DATE(m.event_time)",
            "DATE(m.event_time)>=:a AND DATE(m.event_time)<=:b",
            {"a": da, "b": dbb},
        ),
    ):
        table = f"t_fact_local_entry_flow_{grain}"
        if grain == "hourly":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<:b"), args)
        elif grain == "daily":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<=:b"), args)
        db.execute(
            text(
                f"INSERT INTO {table} ({key},event_count,last_batch_id) "
                f"SELECT {bucket},COUNT(DISTINCT m.event_key),:batch FROM `{m}` m "
                "JOIN t_toll_station s ON s.station_code=m.entry_station_code "
                "JOIN t_local_entry_station l ON l.toll_station_id=s.toll_station_id AND l.enabled=1 "
                f"WHERE {where} GROUP BY {bucket}"
            ),
            {**args, "batch": batch},
        )
    db.execute(
        text("DELETE FROM t_fact_local_entry_flow_monthly WHERE stat_month=:month"),
        {"month": month},
    )
    db.execute(
        text(
            "INSERT INTO t_fact_local_entry_flow_monthly (stat_month,event_count,last_batch_id) SELECT :month,SUM(event_count),:batch FROM t_fact_local_entry_flow_daily WHERE stat_date>=:month AND stat_date<:month_end"
        ),
        {"month": month, "month_end": month_end, "batch": batch},
    )


def _local_entry_station_flow(db, m, ha, hb, da, dbb, month, month_end, batch):
    for grain, key, bucket, where, args in (
        (
            "hourly",
            "stat_hour",
            "DATE_FORMAT(m.event_time,'%Y-%m-%d %H:00:00')",
            "m.event_time>=:a AND m.event_time<:b",
            {"a": ha, "b": hb},
        ),
        (
            "daily",
            "stat_date",
            "DATE(m.event_time)",
            "DATE(m.event_time)>=:a AND DATE(m.event_time)<=:b",
            {"a": da, "b": dbb},
        ),
    ):
        table = f"t_fact_local_entry_station_flow_{grain}"
        if grain == "hourly":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<:b"), args)
        elif grain == "daily":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<=:b"), args)
        db.execute(
            text(
                f"INSERT INTO {table} ({key},toll_station_id,event_count,last_batch_id) "
                f"SELECT {bucket},s.toll_station_id,COUNT(DISTINCT m.event_key),:batch FROM `{m}` m "
                "JOIN t_toll_station s ON s.station_code=m.entry_station_code "
                "JOIN t_local_entry_station l ON l.toll_station_id=s.toll_station_id AND l.enabled=1 "
                f"WHERE {where} GROUP BY {bucket},s.toll_station_id"
            ),
            {**args, "batch": batch},
        )
    db.execute(
        text("DELETE FROM t_fact_local_entry_station_flow_monthly WHERE stat_month=:month"),
        {"month": month},
    )
    db.execute(
        text(
            "INSERT INTO t_fact_local_entry_station_flow_monthly (stat_month,toll_station_id,event_count,last_batch_id) SELECT :month,toll_station_id,SUM(event_count),:batch FROM t_fact_local_entry_station_flow_daily WHERE stat_date>=:month AND stat_date<:month_end GROUP BY toll_station_id"
        ),
        {"month": month, "month_end": month_end, "batch": batch},
    )


def _dimension(db, m, name, cols, select, join, ha, hb, da, dbb, month, month_end, batch):
    for grain, key, bucket, where, args in (
        (
            "hourly",
            "stat_hour",
            "DATE_FORMAT(m.event_time,'%Y-%m-%d %H:00:00')",
            "m.event_time>=:a AND m.event_time<:b",
            {"a": ha, "b": hb},
        ),
        (
            "daily",
            "stat_date",
            "DATE(m.event_time)",
            "DATE(m.event_time)>=:a AND DATE(m.event_time)<=:b",
            {"a": da, "b": dbb},
        ),
    ):
        table = f"t_fact_{name}_{grain}"
        if grain == "hourly":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<:b"), args)
        elif grain == "daily":
            db.execute(text(f"DELETE FROM {table} WHERE {key}>=:a AND {key}<=:b"), args)
        db.execute(
            text(
                f"INSERT INTO {table} (object_no,{key},{cols},event_count,last_batch_id) SELECT m.object_no,{bucket},{select},COUNT(*),:batch FROM `{m}` m {join} WHERE {where} GROUP BY m.object_no,{bucket},{select}"
            ),
            {**args, "batch": batch},
        )
    monthly = f"t_fact_{name}_monthly"
    daily = f"t_fact_{name}_daily"
    db.execute(text(f"DELETE FROM {monthly} WHERE stat_month=:month"), {"month": month})
    db.execute(
        text(
            f"INSERT INTO {monthly} (object_no,stat_month,{cols},event_count,last_batch_id) SELECT object_no,:month,{cols},SUM(event_count),:batch FROM {daily} WHERE stat_date>=:month AND stat_date<:month_end GROUP BY object_no,{cols}"
        ),
        {"month": month, "month_end": month_end, "batch": batch},
    )
