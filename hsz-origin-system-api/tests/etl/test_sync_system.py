from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.api.v1.etl import missing_windows, query_missing_windows
from app.etl import cli, source_reader, sync_service, task_runner
from app.etl.source_schema import source_table
from app.etl.sync_log import start_sync
from app.etl.verifier import center_trade_ids, missing_trade_ids


def server():
    return SimpleNamespace(
        source_server_id=1, server_code="S1", current_table_name="current",
        monthly_table_pattern="history{yyyyMM}", credential_key="source",
        host_address="10.13.1.1", host_port=3306, database_name="etcmj",
    )


@pytest.mark.parametrize(
    ("source", "center", "missing"),
    [
        ({"a", "b"}, {"a", "b"}, set()),
        ({"a", "b"}, {"a", "c"}, {"b"}),
        ({"a"}, {"a", "extra"}, set()),
        (set(), set(), set()),
    ],
)
def test_trade_id_completeness_is_set_difference(source, center, missing):
    assert missing_trade_ids(source, center) == missing


def test_missing_center_month_means_all_source_ids_are_missing():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    assert center_trade_ids(db, {"a", "b"}, "202001") == set()


def test_source_trade_ids_are_deduplicated_and_check_reads_only_three_fields(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchmany.side_effect = [[
        {"trade_id": "a", "gantry_id": "g", "trans_time": datetime(2026, 7, 1)},
        {"trade_id": "a", "gantry_id": "g", "trans_time": datetime(2026, 7, 1)},
    ], []]
    monkeypatch.setattr(source_reader, "source_connection", lambda unused: connection)
    monkeypatch.setattr(source_reader, "inspect_remote", lambda c, t: (
        ["TradeId", "GantryId", "TransTime", "VehiclePlate"], []
    ))
    monkeypatch.setattr(source_reader, "validate_query_index", lambda *a, **k: True)
    rows, metrics = source_reader.read_source_snapshot(
        server(), "current", ["g"], datetime(2026, 7, 1), datetime(2026, 7, 1, 2),
        check_only=True, batch_size=2000, retries=2,
    )
    sql = cursor.execute.call_args.args[0]
    assert len(rows) == 1
    assert metrics["duplicate_count"] == 1
    projection = sql.split("FROM", 1)[0].lower()
    assert "gantry_id" not in projection
    assert "trans_time" not in projection
    assert "vehicle_plate" not in projection
    connection.close.assert_called_once()


def test_non_transient_source_error_is_not_retried(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(source_reader, "source_connection", MagicMock(return_value=connection))
    monkeypatch.setattr(source_reader, "inspect_remote", MagicMock(side_effect=ValueError("bad schema")))
    with pytest.raises(ValueError):
        source_reader.read_source_snapshot(
            server(), "current", ["g"], datetime(2026, 7, 1), datetime(2026, 7, 1, 2),
            check_only=True, batch_size=2000, retries=2,
        )
    assert source_reader.inspect_remote.call_count == 1
    connection.close.assert_called_once()


def test_transient_source_error_gets_two_retries(monkeypatch):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchmany.return_value = []
    connect = MagicMock(side_effect=[ConnectionError("one"), ConnectionError("two"), connection])
    sleeps = []
    monkeypatch.setattr(source_reader, "source_connection", connect)
    monkeypatch.setattr(source_reader, "inspect_remote", lambda *a: (
        ["TradeId", "GantryId", "TransTime"], []
    ))
    monkeypatch.setattr(source_reader, "validate_query_index", lambda *a, **k: True)
    monkeypatch.setattr(source_reader.time, "sleep", sleeps.append)
    source_reader.read_source_snapshot(
        server(), "current", ["g"], datetime(2026, 7, 1), datetime(2026, 7, 1, 2),
        check_only=True, batch_size=2000, retries=2,
    )
    assert connect.call_count == 3
    assert sleeps == [2, 5]


def test_center_retry_reuses_the_same_snapshot(monkeypatch):
    events = [object()]
    writes = MagicMock(side_effect=[RuntimeError("one"), RuntimeError("two"), {"ok": True}])
    sleeps = []

    class Context:
        def __enter__(self): return MagicMock()
        def __exit__(self, *unused): return False
    monkeypatch.setattr(sync_service, "SessionLocal", SimpleNamespace(begin=lambda: Context()))
    monkeypatch.setattr(sync_service, "write_snapshot", writes)
    monkeypatch.setattr(sync_service.time, "sleep", sleeps.append)
    assert sync_service.write_with_retry(events, [], 1) == {"ok": True}
    assert [call.args[1] for call in writes.call_args_list] == [events, events, events]
    assert sleeps == [2, 5]


@pytest.mark.parametrize(
    ("operation", "force", "complete", "expected"),
    [("BACKFILL", False, True, True), ("BACKFILL", True, True, False),
     ("LIVE", False, True, True), ("REPAIR", False, True, False)],
)
def test_resume_and_force_rules(operation, force, complete, expected):
    assert sync_service.should_skip(operation, force, complete) is expected


def test_current_and_past_month_choose_exactly_one_table():
    now = datetime(2026, 7, 23)
    assert source_table(server(), datetime(2026, 7, 1), now) == "current"
    assert source_table(server(), datetime(2026, 6, 1), now) == "history202606"
    assert source_table(server(), datetime(2026, 6, 1), now, "realtime") == "current"
    assert source_table(server(), datetime(2026, 7, 1), now, "history") == "history202607"


def test_explain_accepts_actual_range_key_without_hardcoding_index_order():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"type": "range", "key": "unexpected_real_index"}
    source_reader._index_cache.clear()
    assert source_reader.validate_query_index(
        connection, server(), "current",
        {"trade_id": "TradeId", "gantry_id": "GantryId", "trans_time": "TransTime"},
        required=True, physical_code="g",
    )


def test_each_log_start_generates_a_new_sync_id():
    db = MagicMock()
    db.execute.return_value.lastrowid = 1
    first = start_sync(db, task_no="T", operation="CHECK", server=server(),
                       start=datetime(2026, 7, 1), end=datetime(2026, 7, 1, 2))
    second = start_sync(db, task_no="T", operation="CHECK", server=server(),
                        start=datetime(2026, 7, 1), end=datetime(2026, 7, 1, 2))
    assert first[1] != second[1]
    assert all("INSERT INTO t_etl_sync_log" in call.args[0].text for call in db.execute.call_args_list)


def test_windows_never_cross_month_and_no_recursive_split():
    windows = list(task_runner.iter_windows(datetime(2026, 1, 31, 23),
                                            datetime(2026, 2, 1, 2), 120))
    assert windows == [
        (datetime(2026, 1, 31, 23), datetime(2026, 2, 1)),
        (datetime(2026, 2, 1), datetime(2026, 2, 1, 2)),
    ]
    assert not hasattr(task_runner, "_sync_history_window_with_split")


def test_nightly_d1_d2_are_two_days_and_twenty_four_windows():
    ranges = task_runner.nightly_ranges(datetime(2026, 7, 23, 4, 30))
    assert ranges == [
        (datetime(2026, 7, 22), datetime(2026, 7, 23)),
        (datetime(2026, 7, 21), datetime(2026, 7, 22)),
    ]
    assert sum(len(list(task_runner.iter_windows(a, b))) for a, b in ranges) == 24


def test_cross_month_nightly_windows_resolve_to_history_tables():
    now = datetime(2026, 8, 2)
    ranges = task_runner.nightly_ranges(now)
    tables = {source_table(server(), start, now) for day in ranges
              for start, unused in task_runner.iter_windows(*day)}
    assert tables == {"current", "history202607"}


def test_backfill_rebuilds_a_month_once(monkeypatch):
    monkeypatch.setattr(task_runner, "server_codes", lambda unused=None: ["S1"])
    monkeypatch.setattr(task_runner, "sync_window", lambda *a, **k: {
        "status": "SUCCESS", "check_status": "COMPLETE"
    })
    rebuilt = []
    monkeypatch.setattr(task_runner, "rebuild", lambda db, start, end, log: rebuilt.append(start.strftime("%Y%m")))
    monkeypatch.setattr(task_runner, "ensure_month_tables", lambda *a: None)
    monkeypatch.setattr(task_runner, "month_is_complete", lambda *a: True)

    class Context:
        def __enter__(self): return MagicMock()
        def __exit__(self, *unused): return False
    monkeypatch.setattr(task_runner, "SessionLocal", SimpleNamespace(begin=lambda: Context()))
    result = task_runner.run_range(datetime(2026, 6, 1), datetime(2026, 6, 1, 4),
                                   sleep_seconds=0)
    assert result["processed_windows"] == 2
    assert rebuilt == ["202606"]


def test_missing_windows_query_uses_only_latest_effective_result():
    db = MagicMock()
    db.execute.return_value.mappings.return_value = []
    assert missing_windows(db) == {"items": []}
    sql = db.execute.call_args.args[0].text
    assert "ROW_NUMBER() OVER" in sql
    assert "row_no=1 AND check_status='MISSING'" in sql


def test_new_complete_removes_old_missing_from_latest_results():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE t_etl_sync_log (
                sync_log_id INTEGER PRIMARY KEY, sync_id TEXT, server_code TEXT,
                window_start TEXT, window_end TEXT, source_unique_count INTEGER,
                center_matched_count INTEGER, missing_count INTEGER,
                check_status TEXT, status TEXT
            )
        """))
        connection.execute(text("""
            INSERT INTO t_etl_sync_log VALUES
            (1,'old','S1','2026-07-01 00:00','2026-07-01 02:00',10,9,1,'MISSING','SUCCESS'),
            (2,'new','S1','2026-07-01 00:00','2026-07-01 02:00',10,10,0,'COMPLETE','SUCCESS'),
            (3,'missing','S2','2026-07-01 00:00','2026-07-01 02:00',10,8,2,'MISSING','SUCCESS')
        """))
    with Session(engine) as db:
        assert [row["latest_sync_id"] for row in query_missing_windows(db)] == ["missing"]


def test_repair_by_sync_id_forces_new_repair_execution(monkeypatch):
    row = {"server_code": "S1", "window_start": datetime(2026, 7, 1),
           "window_end": datetime(2026, 7, 1, 2)}
    db = MagicMock()
    db.execute.return_value.mappings.return_value.one_or_none.return_value = row

    class Context:
        def __enter__(self): return db
        def __exit__(self, *unused): return False
    monkeypatch.setattr(task_runner, "SessionLocal", lambda: Context())
    called = MagicMock(return_value={"sync_id": "new"})
    monkeypatch.setattr(task_runner, "sync_window", called)
    assert task_runner.repair_by_sync_id("old") == {"sync_id": "new"}
    called.assert_called_once_with("S1", row["window_start"], row["window_end"],
                                   "REPAIR", True, rebuild_facts=True)


def test_live_once_uses_configured_window_and_safety_delay(monkeypatch, capsys):
    configured = SimpleNamespace(
        live_window_minutes=180, safety_delay=timedelta(minutes=7), poll_seconds=60,
        history_window_minutes=120, history_sleep_seconds=5,
    )
    monkeypatch.setattr(cli, "settings", configured)
    aligned = MagicMock(return_value=(datetime(2026, 7, 1), datetime(2026, 7, 1, 3)))
    monkeypatch.setattr(cli, "aligned_live_window", aligned)
    db = MagicMock()

    class Context:
        def __enter__(self): return db
        def __exit__(self, *unused): return False
    monkeypatch.setattr(cli, "SessionLocal", SimpleNamespace(begin=lambda: Context()))
    monkeypatch.setattr(cli, "enqueue_job", MagicMock(return_value={"status": "PENDING"}))
    monkeypatch.setattr(__import__("sys"), "argv", ["cli", "live-once"])
    cli.main()
    aligned.assert_called_once_with(minutes=180, safety_delay=timedelta(minutes=7))
    assert '"status": "PENDING"' in capsys.readouterr().out


def test_live_window_is_aligned_after_safety_delay():
    assert task_runner.aligned_live_window(
        datetime(2026, 7, 23, 10, 1), safety_delay=timedelta(minutes=2)
    ) == (datetime(2026, 7, 23, 6), datetime(2026, 7, 23, 8))
