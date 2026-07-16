import hashlib
import json
from datetime import datetime

from app.etl.models import Event
from app.etl.previous_gantry import select_previous_gantry
from app.etl.success_policy import is_success


def event_key(source_server_id: int, source_table_name: str, source_trade_id: str) -> bytes:
    value = f"{source_server_id}|{source_table_name}|{source_trade_id}".encode()
    return hashlib.sha256(value).digest()


def normalize(
    row: dict,
    *,
    source_server_id: int,
    source_table_name: str,
    physical_mapping: dict[str, str],
    policy: str,
) -> Event:
    trade_id, event_time, gantry_id = (
        row.get("trade_id"),
        row.get("trans_time"),
        row.get("gantry_id"),
    )
    if not trade_id or not isinstance(event_time, datetime) or not gantry_id:
        raise ValueError("源记录缺少必需字段 TradeId、TransTime 或 GantryId")
    logical = physical_mapping.get(str(gantry_id))
    if not logical:
        raise ValueError("未映射物理门架")
    previous, source, raw = select_previous_gantry(row)
    success, rule = is_success(row, policy)
    return Event(
        event_key(source_server_id, source_table_name, str(trade_id)),
        source_server_id,
        source_table_name,
        str(trade_id),
        event_time,
        str(gantry_id),
        logical,
        previous,
        source,
        json.dumps(raw, ensure_ascii=False),
        str(row["vehicle_type"]) if row.get("vehicle_type") is not None else None,
        row.get("en_toll_hex"),
        str(row["media_type"]) if row.get("media_type") is not None else None,
        str(row["trade_result"]) if row.get("trade_result") is not None else None,
        str(row["obu_trade_result"]) if row.get("obu_trade_result") is not None else None,
        success,
        rule,
    )
