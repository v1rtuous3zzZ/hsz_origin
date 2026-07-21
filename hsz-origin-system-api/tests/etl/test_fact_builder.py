from datetime import datetime
from unittest.mock import Mock

from app.etl.fact_builder import rebuild


def test_monthly_facts_are_aggregated_from_daily_facts() -> None:
    db = Mock()

    rebuild(db, datetime(2026, 7, 21, 10), datetime(2026, 7, 21, 12), 10)

    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    monthly_inserts = [sql for sql in statements if "INSERT INTO" in sql and "_monthly" in sql]
    assert len(monthly_inserts) == 5
    assert all("_daily" in sql for sql in monthly_inserts)
    assert all("t_event_object_match_202607" not in sql for sql in monthly_inserts)
