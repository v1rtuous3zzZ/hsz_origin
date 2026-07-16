import pytest

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
