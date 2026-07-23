import logging
import time
from datetime import datetime
from threading import Lock

import pymysql
from pymysql.cursors import SSDictCursor
from sqlalchemy import text

from app.db.engine import engine
from app.etl.config import source_credentials
from app.etl.source_schema import resolve_columns

logger = logging.getLogger("hsz.etl.source_reader")
_index_cache: dict[tuple[str, str], bool] = {}
_index_cache_lock = Lock()


class SourceQueryIndexError(RuntimeError):
    """源表的有界门架时间查询未使用可接受索引。"""


def is_transient_source_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    return isinstance(error, pymysql.OperationalError) and error.args and error.args[0] in {
        2002, 2003, 2006, 2013
    }


def source_connection(server):
    try:
        username, password = source_credentials(server.credential_key)
        charset = "utf8mb4"
    except RuntimeError:
        with engine.connect() as connection:
            configs = connection.execute(
                text("SELECT username,password,charset FROM t_source_db_config")
            ).mappings().all()
        if len(configs) != 1:
            raise RuntimeError("源环境凭据缺失，且公共凭据配置不是唯一一条")
        username, password, charset = (
            configs[0]["username"], configs[0]["password"], configs[0]["charset"]
        )
    connection = pymysql.connect(
        host=server.host_address, port=server.host_port, user=username, password=password,
        database=server.database_name, charset=charset, cursorclass=SSDictCursor,
        autocommit=True, connect_timeout=10, read_timeout=300, write_timeout=30,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION TRANSACTION READ ONLY")
    return connection


def inspect_remote(connection, table: str) -> tuple[list[str], list[dict]]:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = [row["Field"] for row in cursor.fetchall()]
    resolve_columns(columns)
    return columns, []


def validate_query_index(connection, server, table: str, columns: dict[str, str], *,
                         required: bool, physical_code: str = "__index_probe__") -> bool:
    cache_key = (server.server_code, table)
    with _index_cache_lock:
        cached = _index_cache.get(cache_key)
    if cached is None:
        with connection.cursor() as cursor:
            cursor.execute(
                f"EXPLAIN SELECT `{columns['trade_id']}` FROM `{table}` "
                f"WHERE `{columns['trans_time']}` >= %s AND `{columns['trans_time']}` < %s "
                f"AND `{columns['gantry_id']}` IN (%s)",
                (datetime(2000, 1, 1), datetime(2000, 1, 2), physical_code),
            )
            plan = cursor.fetchone()
        cached = bool(plan.get("key")) and str(plan.get("type", "")).lower() not in {
            "all", "index"
        }
        with _index_cache_lock:
            _index_cache[cache_key] = cached
    if required and not cached:
        raise SourceQueryIndexError(f"源表 {table} 的有界门架时间查询未使用可接受索引")
    return cached


def read_rows(connection, table: str, columns: dict[str, str], physical_codes: list[str],
              start, end, batch_size: int, select_names: tuple[str, ...] | None = None):
    if not physical_codes:
        return
    selected = select_names or tuple(columns)
    select = ", ".join(f"`{columns[name]}` AS `{name}`" for name in selected)
    placeholders = ", ".join(["%s"] * len(physical_codes))
    sql = (
        f"SELECT {select} FROM `{table}` WHERE `{columns['trans_time']}` >= %s "
        f"AND `{columns['trans_time']}` < %s "
        f"AND `{columns['gantry_id']}` IN ({placeholders})"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [start, end, *physical_codes])
        while rows := cursor.fetchmany(batch_size):
            yield from rows


def read_source_snapshot(server, table: str, physical_codes: list[str], start, end, *,
                         check_only: bool, batch_size: int, retries: int) -> tuple[list[dict], dict]:
    """读取单服务器单窗口，返回前关闭连接；只重试瞬时网络错误。"""
    for attempt in range(1, retries + 2):
        connection = None
        started = time.perf_counter()
        try:
            connection = source_connection(server)
            columns, _ = inspect_remote(connection, table)
            resolved = resolve_columns(columns)
            validate_query_index(
                connection, server, table, resolved, required=True,
                physical_code=physical_codes[0],
            )
            rows_by_id: dict[str, dict] = {}
            raw_count = 0
            select_names = ("trade_id",) if check_only else None
            for row in read_rows(
                connection, table, resolved, physical_codes, start, end, batch_size,
                select_names=select_names,
            ):
                raw_count += 1
                rows_by_id.setdefault(str(row["trade_id"]), row)
            return list(rows_by_id.values()), {
                "raw_count": raw_count,
                "unique_count": len(rows_by_id),
                "duplicate_count": raw_count - len(rows_by_id),
                "query_duration_ms": round((time.perf_counter() - started) * 1000),
                "attempt_count": attempt,
            }
        except Exception as error:
            if not is_transient_source_error(error) or attempt > retries:
                raise
            time.sleep(2 if attempt == 1 else 5)
        finally:
            if connection is not None:
                connection.close()
    raise AssertionError("unreachable")
