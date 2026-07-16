import pymysql
from pymysql.cursors import SSDictCursor
from sqlalchemy import text

from app.db.engine import engine
from app.etl.models import SourceServer
from app.etl.source_schema import resolve_columns


def source_connection(server: SourceServer):
    with engine.connect() as connection:
        config = connection.execute(
            text(
                "SELECT port, username, password, db_name, charset FROM t_source_db_config ORDER BY config_id LIMIT 1"
            )
        ).mappings().one_or_none()
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
        read_timeout=120,
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
        cursor.execute(f"SHOW INDEX FROM `{table}`")
        return columns, cursor.fetchall()


def table_exists(connection, table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES LIKE %s", [table])
        return cursor.fetchone() is not None
