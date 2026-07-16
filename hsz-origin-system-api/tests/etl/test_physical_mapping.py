from datetime import datetime

from app.etl.normalizer import normalize


def test_two_physical_gantries_share_one_logical_hex():
    data = {"trade_id": "t", "trans_time": datetime.now(), "gantry_id": "G005032001000810010"}
    first = normalize(
        data,
        source_server_id=1,
        source_table_name="t",
        physical_mapping={"G005032001000810010": "282C08", "G005032001000810020": "282C08"},
        policy="ALL_ROWS_TEST",
    )
    data["gantry_id"] = "G005032001000810020"
    second = normalize(
        data,
        source_server_id=1,
        source_table_name="t",
        physical_mapping={"G005032001000810010": "282C08", "G005032001000810020": "282C08"},
        policy="ALL_ROWS_TEST",
    )
    assert first.current_gantry_hex == second.current_gantry_hex == "282C08"


def test_normalize_keeps_entry_time_and_removes_plate_color_suffix():
    entry_time = datetime(2026, 7, 16, 9, 30)
    event = normalize(
        {
            "trade_id": "t",
            "trans_time": datetime(2026, 7, 16, 10),
            "gantry_id": "G005032001000810010",
            "en_time": entry_time,
            "vehicle_plate": "京A12345_1",
        },
        source_server_id=1,
        source_table_name="t",
        physical_mapping={"G005032001000810010": "282C08"},
        policy="ALL_ROWS_TEST",
    )

    assert event.entry_time == entry_time
    assert event.vehicle_plate_no == "京A12345"
