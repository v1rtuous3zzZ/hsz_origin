import time

from app.etl.match_writer import write_matches
from app.etl.normalizer import normalize
from app.etl.ods_writer import ensure_month_tables, write_events
from app.etl.rule_matcher import match
from app.etl.verifier import center_trade_ids


def normalize_rows(rows, *, server, table: str, physical_mapping: dict[str, str]):
    return [
        normalize(row, source_server_id=server.source_server_id,
                  source_table_name=table, physical_mapping=physical_mapping,
                  policy="MEDIA_SPECIFIC")
        for row in rows
    ]


def write_snapshot(db, events, rules, sync_log_id: int, batch_size: int) -> dict:
    if not events:
        return {"inserted_count": 0, "updated_count": 0, "matched_count": 0,
                "write_duration_ms": 0}
    started = time.perf_counter()
    month = events[0].event_time.strftime("%Y%m")
    ensure_month_tables(db, month)
    trade_ids = {event.source_trade_id for event in events}
    existing = center_trade_ids(db, trade_ids, month, batch_size)
    write_events(db, events, sync_log_id, batch_size)
    matches = []
    for event in events:
        if event.success_flag:
            matches.extend((event, rule) for rule in match(event, rules))
    write_matches(db, matches, sync_log_id, batch_size=batch_size)
    return {
        "inserted_count": len(trade_ids - existing),
        "updated_count": len(existing),
        "matched_count": len(matches),
        "write_duration_ms": round((time.perf_counter() - started) * 1000),
    }
