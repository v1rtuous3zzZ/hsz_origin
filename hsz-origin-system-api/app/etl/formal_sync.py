"""正式门架同步入口。"""

import logging
from collections import Counter
from datetime import datetime

from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.batch_log import finish_batch, start_batch
from app.etl.checkpoint import advance
from app.etl.fact_builder import rebuild
from app.etl.match_writer import write_matches
from app.etl.normalizer import normalize
from app.etl.ods_writer import ensure_month_tables, write_events
from app.etl.rule_matcher import match
from app.etl.source_config import load_mapping, load_rules, load_sources
from app.etl.source_reader import inspect_remote, read_rows, source_connection

logger = logging.getLogger("hsz.etl")


def sync_window(start: datetime, end: datetime, server_code: str | None = None) -> dict:
    """从可达门架源库同步一个单月窗口到中心库。"""
    if start >= end or start.strftime("%Y%m") != end.strftime("%Y%m"):
        raise ValueError("正式同步必须使用同月且结束时间晚于开始时间的窗口")
    metrics = Counter()
    with SessionLocal.begin() as db:
        batch_id, batch_no = start_batch(db, "LIVE_SYNC", "INCREMENTAL", start, end)
    completed_sources = []
    try:
        with SessionLocal.begin() as db:
            ensure_month_tables(db, start.strftime("%Y%m"))
            mapping, rules = load_mapping(db), load_rules(db)
            sources = load_sources(db, server_code)
            for source in sources:
                physical = mapping.get(source.source_server_id, {})
                if not physical:
                    continue
                db.execute(text("INSERT INTO t_etl_batch_source (batch_id,source_server_id,actual_start,actual_end) VALUES (:batch,:source,:start,:end)"), {"batch":batch_id,"source":source.source_server_id,"start":start,"end":end})
                logger.info("batch=%s source=%s start=%s end=%s", batch_no, source.server_code, start, end)
                connection = None
                source_metrics = Counter()
                try:
                    connection = source_connection(source)
                    columns, _ = inspect_remote(connection, source.current_table_name)
                    from app.etl.source_schema import resolve_columns
                    rows = read_rows(connection, source.current_table_name, resolve_columns(columns), list(physical), start, end, 2000)
                    buffer = []
                    for row in rows:
                        source_metrics["source_row_count"] += 1
                        event = normalize(row, source_server_id=source.source_server_id, source_table_name=source.current_table_name, physical_mapping=physical, policy="MEDIA_SPECIFIC")
                        if event.success_flag:
                            buffer.append(event)
                            source_metrics["success_event_count"] += 1
                        if len(buffer) == 2000:
                            matched_count = _write(db, buffer, rules, batch_id)
                            source_metrics["matched_event_count"] += matched_count
                            buffer.clear()
                    source_metrics["matched_event_count"] += _write(db, buffer, rules, batch_id)
                    db.execute(text("UPDATE t_etl_batch_source SET status='SUCCESS',finished_at=NOW(3),source_row_count=:rows,success_event_count=:success,matched_event_count=:matched WHERE batch_id=:batch AND source_server_id=:source"), {"batch":batch_id,"source":source.source_server_id,"rows":source_metrics["source_row_count"],"success":source_metrics["success_event_count"],"matched":source_metrics["matched_event_count"]})
                    metrics += source_metrics
                    completed_sources.append(source.source_server_id)
                finally:
                    if connection:
                        connection.close()
            rebuild(db, start, end, batch_id)
            for source_server_id in completed_sources:
                advance(db, "LIVE_SYNC", source_server_id, end, batch_id)
            finish_batch(db, batch_id, "SUCCESS", metrics)
    except Exception as error:
        logger.exception("batch=%s failed", batch_no)
        with SessionLocal.begin() as db:
            finish_batch(db, batch_id, "FAILED", metrics, str(error)[:2000])
        raise
    return {"batch_no":batch_no, **metrics}


def _write(db, events, rules, batch_id) -> int:
    if not events:
        return 0
    write_events(db, events, batch_id)
    matched_count = 0
    for event in events:
        matched = match(event, rules)
        write_matches(db, event, matched, batch_id)
        matched_count += len(matched)
    return matched_count
