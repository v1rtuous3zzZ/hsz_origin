from dataclasses import fields
from datetime import datetime

from app.etl.models import Event
from app.etl.normalizer import normalize


def test_event_model_only_uses_trade_id() -> None:
    names = {field.name for field in fields(Event)}
    assert "trade_id" in names
    assert "event" + "_key" not in names
    assert "source" + "_trade_id" not in names


def test_normalizer_preserves_raw_trade_id() -> None:
    event = normalize(
        {
            "trade_id": "ABC123",
            "trans_time": datetime(2026, 7, 1),
            "gantry_id": "G1",
        },
        source_server_id=1,
        source_table_name="dfs_gantry_transaction",
        physical_mapping={"G1": "HEX1"},
        policy="MEDIA_SPECIFIC",
    )
    assert event.trade_id == "ABC123"
