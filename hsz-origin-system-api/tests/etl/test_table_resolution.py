from datetime import datetime

import pytest

from app.etl.source_reader import incomplete_realtime_physical_codes, realtime_window_complete
from app.etl.source_schema import monthly_table, resolve_columns


def test_resolves_case_and_underscore_variants():
    assert resolve_columns(["TradeId", "TransTime", "GantryId"]) == {
        "trade_id": "TradeId",
        "trans_time": "TransTime",
        "gantry_id": "GantryId",
    }


def test_missing_required_field_is_clear():
    with pytest.raises(ValueError, match="gantry_id"):
        resolve_columns(["TradeId", "TransTime"])


def test_monthly_name():
    assert (
        monthly_table("dfs_gantry_transaction{yyyyMM}", __import__("datetime").datetime(2026, 7, 1))
        == "dfs_gantry_transaction202607"
    )


def test_continuous_realtime_data_covers_a_two_hour_window():
    start = datetime(2026, 7, 19, 8)
    rows = [{"trans_time": start.replace(minute=minute)} for minute in range(0, 60, 10)]
    rows += [{"trans_time": datetime(2026, 7, 19, 9, minute)} for minute in range(0, 60, 10)]

    assert realtime_window_complete(rows, start, datetime(2026, 7, 19, 10))


def test_gap_in_realtime_data_requires_history_lookup():
    start = datetime(2026, 7, 19, 8)
    rows = [{"trans_time": start.replace(minute=minute)} for minute in range(0, 60, 10)]
    rows += [{"trans_time": datetime(2026, 7, 19, 9, minute)} for minute in range(10, 60, 10)]

    assert not realtime_window_complete(rows, start, datetime(2026, 7, 19, 10))


def test_realtime_completeness_is_checked_for_each_physical_gantry():
    start = datetime(2026, 7, 19, 8)
    rows = [
        {"gantry_id": "complete", "trans_time": start.replace(minute=minute)}
        for minute in range(0, 60, 10)
    ]
    rows += [
        {"gantry_id": "complete", "trans_time": datetime(2026, 7, 19, 9, minute)}
        for minute in range(0, 60, 10)
    ]
    rows += [{"gantry_id": "missing", "trans_time": start}]

    assert incomplete_realtime_physical_codes(
        rows, ["complete", "missing"], start, datetime(2026, 7, 19, 10)
    ) == ["missing"]
