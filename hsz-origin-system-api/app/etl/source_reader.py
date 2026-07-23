import logging
import math
from datetime import datetime
from threading import Lock

import pymysql
from pymysql.cursors import SSDictCursor
from sqlalchemy import text

from app.db.engine import engine
from app.etl.models import SourceServer
from app.etl.source_schema import resolve_columns

logger = logging.getLogger("hsz.etl.source_reader")
_index_cache: dict[tuple[str, str], bool] = {}
_index_cache_lock = Lock()


class SourceQueryIndexError(RuntimeError):
    """源表缺少有界门架时间查询所需的复合索引。"""


def is_transient_source_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    if isinstance(error, pymysql.OperationalError):
        code = error.args[0] if error.args else None
        return code in {2002, 2003, 2006, 2013}
    return False


def source_connection(server: SourceServer):
    """创建门架只读连接；流式游标避免一次性缓存全部结果。"""
    with engine.connect() as connection:
        config = (
            connection.execute(
                text(
                    "SELECT port, username, password, db_name, charset "
                    "FROM t_source_db_config"
                )
            )
            .mappings()
            .all()
        )
    if len(config) != 1:
        raise RuntimeError("t_source_db_config 必须且只能有一条启用的公共凭据配置")
    config = config[0]

    connection = pymysql.connect(
        host=server.host_address,
        port=server.host_port,
        user=config["username"],
        password=config["password"],
        database=server.database_name,
        charset=config["charset"],
        cursorclass=SSDictCursor,
        autocommit=True,
        connect_timeout=10,
        read_timeout=300,
        write_timeout=30,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
    return connection


def validate_query_index(
    connection,
    server: SourceServer,
    table: str,
    columns: dict[str, str],
    *,
    required: bool,
) -> bool:
    """只读检查 `(GantryId, TransTime)` 前缀索引，并按服务器/表缓存。"""
    cache_key = (server.server_code, table)
    with _index_cache_lock:
        cached = _index_cache.get(cache_key)
    if cached is not None:
        if required and not cached:
            raise SourceQueryIndexError(f"源表 {table} 缺少 (GantryId, TransTime) 复合索引")
        return cached

    with connection.cursor() as cursor:
        cursor.execute(f"SHOW INDEX FROM `{table}`")
        rows = cursor.fetchall()
    by_index: dict[str, list[tuple[int, str]]] = {}
    for row in rows:
        by_index.setdefault(str(row["Key_name"]), []).append(
            (int(row["Seq_in_index"]), str(row["Column_name"]).lower())
        )
    expected = [columns["gantry_id"].lower(), columns["trans_time"].lower()]
    valid = any(
        [column for _, column in sorted(parts)][:2] == expected
        for parts in by_index.values()
    )
    with _index_cache_lock:
        _index_cache[cache_key] = valid
    if not valid:
        message = f"源表 {table} 缺少 (GantryId, TransTime) 复合索引"
        if required:
            raise SourceQueryIndexError(message)
        logger.error(message)
    return valid


def read_rows(
    connection,
    table: str,
    columns: dict[str, str],
    physical_codes: list[str],
    start,
    end,
    batch_size: int,
):
    """按门架和有界时间范围走 (GantryId, TransTime, ...) 索引读取。"""
    if not physical_codes:
        return
    select = ", ".join(f"`{actual}` AS `{canonical}`" for canonical, actual in columns.items())
    placeholders = ", ".join(["%s"] * len(physical_codes))
    sql = (
        f"SELECT {select} FROM `{table}` "
        f"WHERE `{columns['trans_time']}` >= %s "
        f"AND `{columns['trans_time']}` < %s "
        f"AND `{columns['gantry_id']}` IN ({placeholders})"
    )
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


def _segment_count(start: datetime, end: datetime) -> int:
    return max(1, math.ceil((end - start).total_seconds() / 600))


def realtime_window_complete(rows: list[dict], start: datetime, end: datetime) -> bool:
    """实时数据覆盖窗口的每个十分钟片段时，才可不查询历史表。"""
    expected_segments = _segment_count(start, end)
    segments = set()
    for row in rows:
        value = row.get("trans_time")
        if not isinstance(value, datetime) or not start <= value < end:
            continue
        segments.add(int((value - start).total_seconds() // 600))
    return len(segments) == expected_segments


def incomplete_realtime_physical_codes(
    rows: list[dict], physical_codes: list[str], start: datetime, end: datetime
) -> list[str]:
    """按每条物理门架返回实时覆盖不完整的门架编号。"""
    expected_segments = _segment_count(start, end)
    segments_by_physical: dict[str, set[int]] = {code: set() for code in physical_codes}
    for row in rows:
        code = str(row.get("gantry_id"))
        value = row.get("trans_time")
        if code not in segments_by_physical or not isinstance(value, datetime):
            continue
        if start <= value < end:
            segments_by_physical[code].add(int((value - start).total_seconds() // 600))
    return [
        code
        for code in physical_codes
        if len(segments_by_physical[code]) != expected_segments
    ]


def realtime_complete_windows(
    connection,
    table: str,
    physical_codes: list[str],
    start: datetime,
    end: datetime,
) -> set[datetime]:
    """返回所有物理门架均覆盖完整十二个十分钟片段的两小时窗口。"""
    columns, _ = inspect_remote(connection, table)
    resolved = resolve_columns(columns)
    placeholders = ", ".join(["%s"] * len(physical_codes))
    time_col = resolved["trans_time"]
    gantry_col = resolved["gantry_id"]
    sql = (
        f"SELECT `{gantry_col}` AS gantry_id, DATE(`{time_col}`) AS stat_date, "
        f"FLOOR(HOUR(`{time_col}`) / 2) AS hour_group, "
        f"MOD(HOUR(`{time_col}`), 2) * 6 + "
        f"FLOOR(MINUTE(`{time_col}`) / 10) AS segment "
        f"FROM `{table}` WHERE `{time_col}` >= %s "
        f"AND `{time_col}` < %s "
        f"AND `{gantry_col}` IN ({placeholders}) "
        f"GROUP BY `{gantry_col}`, DATE(`{time_col}`), "
        f"FLOOR(HOUR(`{time_col}`) / 2), MOD(HOUR(`{time_col}`), 2), "
        f"FLOOR(MINUTE(`{time_col}`) / 10)"
    )
    coverage: dict[datetime, dict[str, set[int]]] = {}
    with connection.cursor() as cursor:
        cursor.execute(sql, [start, end, *physical_codes])
        for row in cursor.fetchall():
            window_start = datetime.combine(row["stat_date"], datetime.min.time()).replace(
                hour=int(row["hour_group"]) * 2
            )
            coverage.setdefault(window_start, {}).setdefault(
                str(row["gantry_id"]), set()
            ).add(int(row["segment"]))

    expected = set(physical_codes)
    return {
        window_start
        for window_start, by_gantry in coverage.items()
        if set(by_gantry) == expected
        and all(len(by_gantry[code]) == 12 for code in physical_codes)
    }


def window_counts(
    connection,
    tables: list[str],
    physical_codes: list[str],
    start,
    end,
) -> dict[datetime, int]:
    """跨实时表/月表按 TradeId 去重后汇总两小时源端数量。"""
    if not tables or not physical_codes:
        return {}

    selects = []
    params = []
    for table in tables:
        columns, _ = inspect_remote(connection, table)
        resolved = resolve_columns(columns)
        placeholders = ", ".join(["%s"] * len(physical_codes))
        selects.append(
            f"SELECT `{resolved['trade_id']}` AS trade_id, "
            f"`{resolved['trans_time']}` AS trans_time "
            f"FROM `{table}` WHERE `{resolved['trans_time']}` >= %s "
            f"AND `{resolved['trans_time']}` < %s "
            f"AND `{resolved['gantry_id']}` IN ({placeholders})"
        )
        params.extend([start, end, *physical_codes])

    union_sql = " UNION ALL ".join(selects)
    sql = (
        "SELECT DATE(trans_time) AS stat_date, "
        "FLOOR(HOUR(trans_time) / 2) AS hour_group, "
        "COUNT(DISTINCT trade_id) AS row_count "
        f"FROM ({union_sql}) source_rows "
        "GROUP BY DATE(trans_time), FLOOR(HOUR(trans_time) / 2)"
    )
    counts = {}
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        for row in cursor.fetchall():
            window_start = datetime.combine(
                row["stat_date"], datetime.min.time()
            ).replace(hour=int(row["hour_group"]) * 2)
            counts[window_start] = int(row["row_count"])
    return counts
