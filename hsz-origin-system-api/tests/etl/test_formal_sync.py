from contextlib import nullcontext
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.etl.formal_sync import _collect_source, _collect_sources, sync_window
from app.etl.models import Event, SourceServer


class FakeConnection:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_lock_waiter_skips_source_read_when_window_completed() -> None:
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", None, "key")
    db = MagicMock()
    with (
        patch("app.etl.formal_sync.SessionLocal.begin", return_value=nullcontext(db)),
        patch("app.etl.formal_sync.ensure_month_tables"),
        patch("app.etl.formal_sync.load_mapping", return_value={1: {"g1": "hex"}}),
        patch("app.etl.formal_sync.load_rules", return_value=[]),
        patch("app.etl.formal_sync.load_sources", return_value=[source]),
        patch("app.etl.formal_sync.source_read_lock", return_value=nullcontext()),
        patch("app.etl.formal_sync.successful_server_codes", return_value={"source"}),
        patch("app.etl.formal_sync.start_batch") as start_batch,
        patch("app.etl.formal_sync._collect_sources") as collect,
    ):
        result = sync_window(datetime(2026, 7, 21, 10), datetime(2026, 7, 21, 12))

    assert result["status"] == "SKIPPED"
    start_batch.assert_not_called()
    collect.assert_not_called()


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
        patch("app.etl.formal_sync.validate_query_index", return_value=True),
        patch("app.etl.formal_sync.read_rows", return_value=iter([row])),
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


def test_low_traffic_auto_window_does_not_scan_history_table() -> None:
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", "history{yyyyMM}", "key")
    connection = FakeConnection()
    with (
        patch("app.etl.formal_sync.source_connection", return_value=connection),
        patch("app.etl.formal_sync._resolved_source_columns", return_value={}),
        patch("app.etl.formal_sync.validate_query_index", return_value=True),
        patch("app.etl.formal_sync.read_rows", return_value=iter([])) as read,
    ):
        result = _collect_source(
            source, {"g1": "hex"}, datetime(2026, 7, 21, 10), datetime(2026, 7, 21, 12), "AUTO"
        )

    assert result[4] == "REALTIME"
    assert read.call_count == 1


def test_non_retryable_source_error_stops_immediately() -> None:
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", None, "key")
    with (
        patch("app.etl.formal_sync.source_connection", side_effect=ValueError("字段缺失")) as connect,
        patch("app.etl.formal_sync.time.sleep") as sleep,
    ):
        result = _collect_source(
            source, {"g1": "hex"}, datetime(2026, 7, 21, 10), datetime(2026, 7, 21, 12), "AUTO", retries=3
        )

    assert result[3] and "ValueError" in result[3]
    assert connect.call_count == 1
    sleep.assert_not_called()


def test_transient_source_error_retries_with_backoff() -> None:
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", None, "key")
    connection = FakeConnection()
    with (
        patch("app.etl.formal_sync.source_connection", side_effect=[TimeoutError("slow"), connection]) as connect,
        patch("app.etl.formal_sync._resolved_source_columns", return_value={}),
        patch("app.etl.formal_sync.validate_query_index", return_value=True),
        patch("app.etl.formal_sync.read_rows", return_value=iter([])),
        patch("app.etl.formal_sync.time.sleep") as sleep,
    ):
        result = _collect_source(
            source, {"g1": "hex"}, datetime(2026, 7, 21, 10), datetime(2026, 7, 21, 12), "AUTO", retries=2
        )

    assert result[3] is None
    assert connect.call_count == 2
    sleep.assert_called_once_with(2)


def test_same_ip_sources_are_serialized() -> None:
    import threading
    import time

    sources = [
        (SourceServer(i, f"s{i}", "10.13.0.1", 3306, f"db{i}", "current", None, "key"), {"g": "h"})
        for i in (1, 2)
    ]
    active = 0
    peak = 0
    guard = threading.Lock()

    def collect(*args, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with guard:
            active -= 1
        return (args[0], {}, [], None, "AUTO")

    with patch("app.etl.formal_sync._collect_source", side_effect=collect):
        _collect_sources(sources, datetime(2026, 1, 1), datetime(2026, 1, 1, 2), {}, 2000, 2, 1, "AUTO")

    assert peak == 1


def test_different_ips_respect_max_worker_limit() -> None:
    import threading
    import time

    sources = [
        (SourceServer(i, f"s{i}", f"10.13.0.{i}", 3306, f"db{i}", "current", None, "key"), {"g": "h"})
        for i in (1, 2, 3)
    ]
    active = 0
    peak = 0
    guard = threading.Lock()

    def collect(*args, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.03)
        with guard:
            active -= 1
        return (args[0], {}, [], None, "AUTO")

    with patch("app.etl.formal_sync._collect_source", side_effect=collect):
        _collect_sources(sources, datetime(2026, 1, 1), datetime(2026, 1, 1, 2), {}, 2000, 2, 1, "AUTO")

    assert peak == 2


def test_mixed_mode_keeps_realtime_priority_and_deduplicates_trade_id() -> None:
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", "history{yyyyMM}", "key")
    connection = FakeConnection()
    realtime = [
        {"trade_id": "same", "gantry_id": "g1", "trans_time": datetime(2026, 7, 1)},
        {"trade_id": "live", "gantry_id": "g1", "trans_time": datetime(2026, 7, 1)},
    ]
    history = [
        {"trade_id": "same", "gantry_id": "g1", "trans_time": datetime(2026, 7, 1)},
        {"trade_id": "history", "gantry_id": "g1", "trans_time": datetime(2026, 7, 1)},
    ]
    events = []

    def normalize_row(row, **kwargs):
        event = MagicMock(success_flag=True, source_trade_id=row["trade_id"], source_table_name=kwargs["source_table_name"])
        events.append(event)
        return event

    with (
        patch("app.etl.formal_sync.source_connection", return_value=connection),
        patch("app.etl.formal_sync._resolved_source_columns", return_value={}),
        patch("app.etl.formal_sync.validate_query_index", return_value=True),
        patch("app.etl.formal_sync.read_rows", side_effect=[iter(realtime), iter(history)]),
        patch("app.etl.formal_sync.normalize", side_effect=normalize_row),
    ):
        result = _collect_source(
            source, {"g1": "hex"}, datetime(2026, 7, 1), datetime(2026, 7, 1, 2), "MIXED"
        )

    assert result[1]["raw_source_row_count"] == 4
    assert result[1]["source_row_count"] == 3
    assert result[1]["duplicate_source_row_count"] == 1
    same = next(event for event in events if event.source_trade_id == "same")
    assert same.source_table_name == "current"


def test_history_mode_reads_only_monthly_table() -> None:
    source = SourceServer(1, "source", "10.13.0.1", 3306, "etcmj", "current", "history{yyyyMM}", "key")
    connection = FakeConnection()
    with (
        patch("app.etl.formal_sync.source_connection", return_value=connection),
        patch("app.etl.formal_sync._resolved_source_columns", return_value={}),
        patch("app.etl.formal_sync.validate_query_index", return_value=True),
        patch("app.etl.formal_sync.read_rows", return_value=iter([])) as read,
    ):
        result = _collect_source(
            source, {"g1": "hex"}, datetime(2026, 1, 1), datetime(2026, 1, 1, 2), "HISTORY"
        )

    assert result[4] == "HISTORY"
    assert read.call_count == 1
    assert read.call_args.args[1] == "history202601"
