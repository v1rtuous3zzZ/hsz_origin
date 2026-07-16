import hashlib
import json
from datetime import datetime

from app.etl.models import Event
from app.etl.previous_gantry import select_previous_gantry
from app.etl.success_policy import is_success


def event_key(source_server_id: int, source_table_name: str, source_trade_id: str) -> bytes:
    value = f"{source_server_id}|{source_table_name}|{source_trade_id}".encode()
    return hashlib.sha256(value).digest()


def plate_number(value: object) -> str | None:
    if value is None:
        return None
    plate = str(value).strip()
    if not plate:
        return None
    return plate.rsplit("_", 1)[0]


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
        event_key=event_key(source_server_id, source_table_name, str(trade_id)),
        source_server_id=source_server_id,
        source_table_name=source_table_name,
        source_trade_id=str(trade_id),
        event_time=event_time,
        current_physical_gantry_code=str(gantry_id),
        current_gantry_hex=logical,
        previous_gantry_hex=previous,
        previous_gantry_source=source,
        raw_previous_gantry_json=json.dumps(raw, ensure_ascii=False),
        vehicle_type_code=str(row["vehicle_type"]) if row.get("vehicle_type") is not None else None,
        entry_station_code=row.get("en_toll_hex"),
        media_type=str(row["media_type"]) if row.get("media_type") is not None else None,
        trade_result=str(row["trade_result"]) if row.get("trade_result") is not None else None,
        obu_trade_result=str(row["obu_trade_result"]) if row.get("obu_trade_result") is not None else None,
        success_flag=success,
        success_rule_code=rule,
        entry_time=row.get("en_time"),
        vehicle_plate_no=plate_number(row.get("vehicle_plate")),
    )
