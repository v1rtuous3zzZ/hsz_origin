from collections import Counter
from datetime import datetime, timedelta

import pymysql
from pymysql.cursors import SSDictCursor
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.etl.config import EtlSettings
from app.etl.normalizer import normalize
from app.etl.rule_matcher import match
from app.etl.source_config import load_mapping, load_rules, load_sources
from app.etl.source_reader import read_rows, source_connection
from app.etl.success_policy import select_policy


def windows(start: datetime, end: datetime, minutes: int):
    while start < end:
        next_end = min(start + timedelta(minutes=minutes), end)
        yield start, next_end
        start = next_end


def legacy_connection():
    s = get_settings()
    return pymysql.connect(
        host=s.db_host,
        port=s.db_port,
        user=s.db_user,
        password=s.db_password,
        database="hsz_origin_sys",
        charset="utf8mb4",
        cursorclass=SSDictCursor,
    )


def dry_run(
    db: Session,
    start: datetime,
    end: datetime,
    source_mode: str,
    server_code: str | None = None,
    batch_size: int | None = None,
) -> dict:
    policy = select_policy(source_mode)
    settings = EtlSettings()
    sources, mapping, rules = load_sources(db, server_code), load_mapping(db), load_rules(db)
    stats, matches, previous = Counter(), Counter(), Counter()
    for source in sources:
        physical = mapping.get(source.source_server_id, {})
        if not physical:
            continue
        if source_mode == "legacy-test":
            connection, table = legacy_connection(), "t_gantry_transaction"
            query_columns = {
                "trade_id": "trade_id",
                "trans_time": "trans_time",
                "gantry_id": "gantry_id",
                "vehicle_type": "vehicle_type",
                "last_gantry_hex": "last_gantry_hex",
                "last_gantry_hex_pass": "last_gantry_hex_pass",
                "obu_last_gantry_hex": "OBU_last_gantry_hex",
                "fee_prov_begin_hex": "fee_prov_begin_hex",
                "en_toll_hex": "en_toll_hex",
                "media_type": "media_type",
                "trade_result": "trade_result",
                "obu_trade_result": "OBU_trade_result",
            }
            sql_source = source.host_address
            iterator = _legacy_rows(
                connection,
                query_columns,
                list(physical),
                start,
                end,
                batch_size or settings.batch_size,
                sql_source,
            )
        else:
            connection, table = source_connection(source), source.current_table_name
            from app.etl.source_reader import inspect_remote

            columns, _ = inspect_remote(source, table)
            from app.etl.source_schema import resolve_columns

            iterator = read_rows(
                connection,
                table,
                resolve_columns(columns),
                list(physical),
                start,
                end,
                batch_size or settings.batch_size,
            )
        try:
            for row in iterator:
                stats["source_rows"] += 1
                try:
                    event = normalize(
                        row,
                        source_server_id=source.source_server_id,
                        source_table_name=table,
                        physical_mapping=physical,
                        policy=policy,
                    )
                except ValueError as error:
                    stats[str(error)] += 1
                    continue
                stats["normalized"] += 1
                if event.success_flag:
                    stats["success"] += 1
                if event.previous_gantry_source:
                    previous[event.previous_gantry_source] += 1
                for rule in match(event, rules):
                    matches[rule.object_no] += 1
        finally:
            connection.close()
    return {
        "sources": len(sources),
        "physical_gantries": sum(map(len, mapping.values())),
        "stats": dict(stats),
        "previous_sources": dict(previous),
        "object_matches": dict(matches),
    }


def _legacy_rows(connection, columns, physical, start, end, batch_size, host):
    placeholders = ",".join(["%s"] * len(physical))
    sql = f"SELECT trade_id,trans_time,gantry_id,vehicle_type,last_gantry_hex,last_gantry_hex_pass,OBU_last_gantry_hex AS obu_last_gantry_hex,fee_prov_begin_hex,en_toll_hex,media_type,trade_result,OBU_trade_result AS obu_trade_result FROM t_gantry_transaction WHERE src_host=%s AND trans_time>=%s AND trans_time<%s AND gantry_id IN ({placeholders}) ORDER BY trans_time,trade_id"
    with connection.cursor() as cursor:
        cursor.execute(sql, [host, start, end, *physical])
        while rows := cursor.fetchmany(batch_size):
            yield from rows
