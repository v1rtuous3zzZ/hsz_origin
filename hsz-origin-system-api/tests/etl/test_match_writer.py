from datetime import datetime
from unittest.mock import Mock

from app.etl.match_writer import write_matches
from app.etl.models import Event, Rule


def test_write_matches_uses_one_bulk_execute() -> None:
    db = Mock()
    event = Event(
        trade_id="trade",
        source_server_id=1,
        source_table_name="source",
        event_time=datetime(2026, 7, 21, 10),
        entry_time=None,
        vehicle_plate_no=None,
        current_physical_gantry_code="gantry",
        current_gantry_hex=None,
        previous_gantry_hex=None,
        previous_gantry_source=None,
        raw_previous_gantry_json=None,
        vehicle_type_code=None,
        entry_station_code=None,
        media_type=None,
        trade_result=None,
        obu_trade_result=None,
        success_flag=True,
        success_rule_code="rule",
    )
    rules = [
        Rule(1, 1, "ENTRY", None, "current", datetime(2026, 1, 1), None),
        Rule(2, 2, "ENTRY", None, "current", datetime(2026, 1, 1), None),
    ]

    write_matches(db, [(event, rule) for rule in rules], batch_id=10)

    db.execute.assert_called_once()
    assert len(db.execute.call_args.args[1]) == 2
    sql = str(db.execute.call_args.args[0])
    assert "trade_id" in sql
    assert "event" + "_key" not in sql
