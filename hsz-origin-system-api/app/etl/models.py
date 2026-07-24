from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceServer:
    source_server_id: int
    server_code: str
    host_address: str
    host_port: int
    database_name: str
    current_table_name: str
    monthly_table_pattern: str | None
    credential_key: str


@dataclass(frozen=True)
class Rule:
    rule_no: int
    object_no: int
    rule_type: str
    previous_gantry_hex: str | None
    current_gantry_hex: str
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True)
class Event:
    trade_id: str
    source_server_id: int
    source_table_name: str
    event_time: datetime
    current_physical_gantry_code: str
    current_gantry_hex: str
    previous_gantry_hex: str | None
    previous_gantry_source: str | None
    raw_previous_gantry_json: str
    vehicle_type_code: str | None
    entry_station_code: str | None
    media_type: str | None
    trade_result: str | None
    obu_trade_result: str | None
    success_flag: bool
    success_rule_code: str
    entry_time: datetime | None = None
    vehicle_plate_no: str | None = None
