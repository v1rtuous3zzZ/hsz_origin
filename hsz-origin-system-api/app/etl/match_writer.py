from sqlalchemy import text
from sqlalchemy.orm import Session

from app.etl.models import Event, Rule


def write_matches(
    db: Session,
    matches: list[tuple[Event, Rule]],
    batch_id: int,
    category: str = "UNKNOWN",
):
    if not matches:
        return
    table = f"t_event_object_match_{matches[0][0].event_time:%Y%m}"
    db.execute(
        text(
            f"INSERT IGNORE INTO `{table}` (event_key,event_time,source_server_id,source_trade_id,object_no,rule_no,previous_gantry_hex,current_gantry_hex,entry_station_code,vehicle_type_code,vehicle_category_code,batch_id) VALUES (:key,:time,:server,:trade,:object_no,:rule_no,:previous,:current,:station,:vehicle,:category,:batch)"
        ),
        [
            {
                "key": event.event_key,
                "time": event.event_time,
                "server": event.source_server_id,
                "trade": event.source_trade_id,
                "object_no": rule.object_no,
                "rule_no": rule.rule_no,
                "previous": event.previous_gantry_hex,
                "current": event.current_gantry_hex,
                "station": event.entry_station_code,
                "vehicle": event.vehicle_type_code,
                "category": category,
                "batch": batch_id,
            }
            for event, rule in matches
        ],
    )
