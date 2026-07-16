from contextlib import closing

import pymysql
from pymysql.cursors import SSDictCursor

from app.etl.config import source_credentials
from app.etl.models import SourceServer
from app.etl.source_schema import resolve_columns


def source_connection(server: SourceServer):
    user, password = source_credentials(server.credential_key)
    return pymysql.connect(
        host=server.host_address,
        port=server.host_port,
        user=user,
        password=password,
        database=server.database_name,
        charset="utf8mb4",
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
    sql = f"SELECT {select} FROM `{table}` WHERE `{columns['trans_time']}` >= %s AND `{columns['trans_time']}` < %s AND `{columns['gantry_id']}` IN ({placeholders}) ORDER BY `{columns['trans_time']}`, `{columns['trade_id']}`"
    with connection.cursor() as cursor:
        cursor.execute(sql, [start, end, *physical_codes])
        while rows := cursor.fetchmany(batch_size):
            yield from rows


def inspect_remote(server: SourceServer, table: str) -> tuple[list[str], list[dict]]:
    with closing(source_connection(server)) as connection, connection.cursor() as cursor:
        cursor.execute(f"SHOW COLUMNS FROM `{table}`")
        columns = [row["Field"] for row in cursor.fetchall()]
        resolve_columns(columns)
        cursor.execute(f"SHOW INDEX FROM `{table}`")
        return columns, cursor.fetchall()
