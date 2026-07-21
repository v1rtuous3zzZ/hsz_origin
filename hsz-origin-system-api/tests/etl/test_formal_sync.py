from datetime import datetime
from unittest.mock import patch

from app.etl.formal_sync import _collect_source
from app.etl.models import Event, SourceServer


class FakeConnection:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_source_connection_is_closed_before_normalization() -> None:
    connection = FakeConnection()
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", None, "key")
    row = {"trade_id": "trade", "trans_time": datetime(2026, 7, 21, 10), "gantry_id": "g1"}
    event = Event(
        event_key=b"key",
        source_server_id=1,
        source_table_name="current",
        source_trade_id="trade",
        event_time=row["trans_time"],
        current_physical_gantry_code="g1",
        current_gantry_hex="hex",
        previous_gantry_hex=None,
        previous_gantry_source=None,
        raw_previous_gantry_json="{}",
        vehicle_type_code=None,
        entry_station_code=None,
        media_type=None,
        trade_result=None,
        obu_trade_result=None,
        success_flag=True,
        success_rule_code="rule",
    )

    def normalize_after_close(*args, **kwargs):
        assert connection.closed
        return event

    with (
        patch("app.etl.formal_sync.source_connection", return_value=connection),
        patch("app.etl.formal_sync._resolved_source_columns", return_value={}),
        patch("app.etl.formal_sync.read_rows", return_value=iter([row])),
        patch("app.etl.formal_sync.incomplete_realtime_physical_codes", return_value=[]),
        patch("app.etl.formal_sync.normalize", side_effect=normalize_after_close),
    ):
        result = _collect_source(
            source,
            {"g1": "hex"},
            datetime(2026, 7, 21, 10),
            datetime(2026, 7, 21, 12),
            "AUTO",
        )

    assert result[1]["source_row_count"] == 1
    assert result[2] == [event]
    assert result[3] is None
