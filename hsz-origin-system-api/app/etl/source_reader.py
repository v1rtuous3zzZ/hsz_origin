from datetime import datetime

import pymysql
from pymysql.cursors import SSDictCursor
from sqlalchemy import text

from app.db.engine import engine
from app.etl.models import SourceServer
from app.etl.source_schema import resolve_columns


def source_connection(server: SourceServer):
    with engine.connect() as connection:
        config = (
            connection.execute(
                text(
                    "SELECT port, username, password, db_name, charset FROM t_source_db_config ORDER BY config_id LIMIT 1"
                )
            )
            .mappings()
            .one_or_none()
        )
    if not config:
        raise RuntimeError("中心库缺少 t_source_db_config 门架源库连接配置")
    return pymysql.connect(
        host=server.host_address,
        port=config["port"],
        user=config["username"],
        password=config["password"],
        database=config["db_name"],
        charset=config["charset"],
        cursorclass=SSDictCursor,
        connect_timeout=10,
        read_timeout=300,
    )


def read_rows(
    connection,
    table: str,
    columns: dict[str, str],
    physical_codes: list[str],
    start,
    end,
    batch_size: int,
):
    """Read one bounded source slice through the (GantryId, TransTime, ...) index."""
    select = ", ".join(f"`{actual}` AS `{canonical}`" for canonical, actual in columns.items())
    placeholders = ", ".join(["%s"] * len(physical_codes))
    sql = f"SELECT {select} FROM `{table}` WHERE `{columns['trans_time']}` >= %s AND `{columns['trans_time']}` < %s AND `{columns['gantry_id']}` IN ({placeholders})"
    with connection.cursor() as cursor:
        cursor.execute(sql, [start, end, *physical_codes])
        while rows := cursor.fetchmany(batch_size):
            yield from rows


def inspect_remote(connection, table: str) -> tuple[list[str], list[dict]]:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = [row["Field"] for row in cursor.fetchall()]
        resolve_columns(columns)
        return columns, []


def realtime_window_complete(rows: list[dict], start: datetime, end: datetime) -> bool:
    """实时数据覆盖窗口的每个十分钟片段时，才可不查询历史表。"""
    expected_segments = int((end - start).total_seconds() // 600)
    segments = set()
    for row in rows:
        value = row["trans_time"]
        if not isinstance(value, datetime) or not start <= value < end:
            continue
        segments.add(int((value - start).total_seconds() // 600))
    return len(segments) == expected_segments


def incomplete_realtime_physical_codes(
    rows: list[dict], physical_codes: list[str], start: datetime, end: datetime
) -> list[str]:
    """返回未覆盖完整两小时窗口的物理门架。"""
    by_physical: dict[str, list[dict]] = {code: [] for code in physical_codes}
    for row in rows:
        code = str(row.get("gantry_id"))
        if code in by_physical:
            by_physical[code].append(row)
    return [
        code
        for code, physical_rows in by_physical.items()
        if not realtime_window_complete(physical_rows, start, end)
    ]


def realtime_complete_windows(
    connection,
    table: str,
    physical_codes: list[str],
    start: datetime,
    end: datetime,
) -> set[datetime]:
    """只扫描时间桶，找出实时表连续覆盖的两小时窗口。"""
    columns, _ = inspect_remote(connection, table)
    resolved = resolve_columns(columns)
    placeholders = ", ".join(["%s"] * len(physical_codes))
    sql = (
        f"SELECT DATE(`{resolved['trans_time']}`) AS stat_date, "
        f"FLOOR(HOUR(`{resolved['trans_time']}`) / 2) AS hour_group, "
        f"MOD(HOUR(`{resolved['trans_time']}`), 2) * 6 + "
        f"FLOOR(MINUTE(`{resolved['trans_time']}`) / 10) AS segment "
        f"FROM `{table}` WHERE `{resolved['trans_time']}` >= %s "
        f"AND `{resolved['trans_time']}` < %s "
        f"AND `{resolved['gantry_id']}` IN ({placeholders}) "
        "GROUP BY DATE(`{0}`), FLOOR(HOUR(`{0}`) / 2), "
        "MOD(HOUR(`{0}`), 2), FLOOR(MINUTE(`{0}`) / 10)"
    ).format(resolved["trans_time"])
    windows: dict[datetime, set[int]] = {}
    with connection.cursor() as cursor:
        cursor.execute(sql, [start, end, *physical_codes])
        for row in cursor.fetchall():
            window_start = datetime.combine(row["stat_date"], datetime.min.time()).replace(
                hour=int(row["hour_group"]) * 2
            )
            windows.setdefault(window_start, set()).add(int(row["segment"]))
    return {window_start for window_start, segments in windows.items() if len(segments) == 12}


def window_counts(connection, tables: list[str], physical_codes: list[str], start, end) -> dict:
    """按两小时窗口汇总源端交易数，用于凌晨核对，不返回交易明细。"""
    counts = {}
    for table in tables:
        columns, _ = inspect_remote(connection, table)
        resolved = resolve_columns(columns)
        placeholders = ", ".join(["%s"] * len(physical_codes))
        sql = (
            f"SELECT DATE(`{resolved['trans_time']}`) AS stat_date, "
            f"FLOOR(HOUR(`{resolved['trans_time']}`) / 2) AS hour_group, "
            f"COUNT(DISTINCT `{resolved['trade_id']}`) AS row_count "
            f"FROM `{table}` WHERE `{resolved['trans_time']}` >= %s "
            f"AND `{resolved['trans_time']}` < %s "
            f"AND `{resolved['gantry_id']}` IN ({placeholders}) "
            f"GROUP BY DATE(`{resolved['trans_time']}`), FLOOR(HOUR(`{resolved['trans_time']}`) / 2)"
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, [start, end, *physical_codes])
            for row in cursor.fetchall():
                window_start = datetime.combine(
                    row["stat_date"],
                    datetime.min.time(),
                ).replace(hour=int(row["hour_group"]) * 2)
                counts[window_start] = max(counts.get(window_start, 0), row["row_count"])
    return counts
