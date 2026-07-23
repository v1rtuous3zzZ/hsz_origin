import re
from pathlib import Path

MIGRATION = Path(__file__).parents[2] / "migrations" / "20260723_simplify_etl.sql"
FACT_TABLES = {
    f"t_fact_{name}_{grain}"
    for name in (
        "flow",
        "local_entry_flow",
        "local_entry_station_flow",
        "source_station",
        "vehicle_type",
    )
    for grain in ("hourly", "daily", "monthly")
}


def test_trade_id_migration_clears_all_rebuildable_fact_data_only():
    sql = MIGRATION.read_text(encoding="utf-8")
    deleted = set(re.findall(r"DELETE FROM (t_fact_[a-z_]+);", sql))
    dropped = set(re.findall(r"DROP TABLE IF EXISTS (t_fact_[a-z_]+);", sql))
    assert deleted == FACT_TABLES
    assert not dropped


def test_trade_id_migration_has_no_redundant_trade_id_indexes():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "PRIMARY KEY (trade_id)" in sql
    assert "uk_ods_trade_id" not in sql
    assert "UNIQUE KEY uk_event_object_match (trade_id,object_no)" in sql
    assert "idx_match_trade_id" not in sql
