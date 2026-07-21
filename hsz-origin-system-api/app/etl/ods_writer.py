from sqlalchemy import text
from sqlalchemy.orm import Session

from app.etl.models import Event


def ensure_month_tables(db: Session, month: str):
    db.execute(text("CALL sp_create_event_month_tables(:month)"), {"month": month})


def write_events(db: Session, events: list[Event], batch_id: int):
    """Bulk-upsert center ODS rows; uk_ods_event_key provides idempotency."""
    if not events:
        return
    table = f"t_ods_event_{events[0].event_time:%Y%m}"
    statement = text(
        f"INSERT INTO `{table}` (event_key,source_server_id,source_table_name,source_trade_id,event_time,entry_time,vehicle_plate_no,current_physical_gantry_code,current_gantry_hex,previous_gantry_hex,previous_gantry_source,raw_previous_gantry_json,vehicle_type_code,entry_station_code,media_type,trade_result,obu_trade_result,success_flag,success_rule_code,batch_id) VALUES (:event_key,:source_server_id,:source_table_name,:source_trade_id,:event_time,:entry_time,:vehicle_plate_no,:current_physical_gantry_code,:current_gantry_hex,:previous_gantry_hex,:previous_gantry_source,:raw_previous_gantry_json,:vehicle_type_code,:entry_station_code,:media_type,:trade_result,:obu_trade_result,:success_flag,:success_rule_code,:batch_id) ON DUPLICATE KEY UPDATE entry_time=COALESCE(VALUES(entry_time),entry_time),vehicle_plate_no=COALESCE(VALUES(vehicle_plate_no),vehicle_plate_no)"
    )
    db.execute(statement, [{**event.__dict__, "batch_id": batch_id} for event in events])
