from datetime import datetime

from app.etl.models import Event, Rule
from app.etl.rule_matcher import match


def event(previous="AAAAAA"):
    return Event(
        trade_id="id",
        source_server_id=1,
        source_table_name="t",
        event_time=datetime(2026, 1, 1),
        current_physical_gantry_code="p",
        current_gantry_hex="BBBBBB",
        previous_gantry_hex=previous,
        previous_gantry_source=None,
        raw_previous_gantry_json="{}",
        vehicle_type_code=None,
        entry_station_code=None,
        media_type=None,
        trade_result=None,
        obu_trade_result=None,
        success_flag=True,
        success_rule_code="TEST",
    )


def rule(no, obj, kind, previous=None):
    return Rule(no, obj, kind, previous, "BBBBBB", datetime(2020, 1, 1), None)


def test_matches_current_and_previous_without_duplicate_object():
    assert [
        r.object_no
        for r in match(
            event(),
            [
                rule(1, 110, "CURRENT_ONLY"),
                rule(2, 110, "PREVIOUS_TO_CURRENT", "AAAAAA"),
                rule(3, 111, "PREVIOUS_TO_CURRENT", "AAAAAA"),
            ],
        )
    ] == [110, 111]
