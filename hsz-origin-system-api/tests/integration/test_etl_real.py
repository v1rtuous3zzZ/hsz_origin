import os
from datetime import datetime

import pytest
from sqlalchemy import text

from app.db.session import SessionLocal
from app.etl.sync_service import sync_window

pytestmark = pytest.mark.skipif(
    os.getenv("HSZ_RUN_ETL_INTEGRATION") != "1",
    reason="set HSZ_RUN_ETL_INTEGRATION=1 to access the configured center and read-only source",
)


def test_repair_creates_new_log_and_does_not_duplicate_trade_id() -> None:
    server = os.environ["HSZ_TEST_SERVER_CODE"]
    start = datetime.fromisoformat(os.environ["HSZ_TEST_WINDOW_START"])
    end = datetime.fromisoformat(os.environ["HSZ_TEST_WINDOW_END"])
    first = sync_window(server, start, end, "REPAIR", True, rebuild_facts=True)
    second = sync_window(server, start, end, "REPAIR", True, rebuild_facts=True)
    assert first["sync_id"] != second["sync_id"]
    assert first["check_status"] == second["check_status"] == "COMPLETE"
    with SessionLocal() as db:
        counts = db.execute(
            text(
                f"SELECT COUNT(*) row_count,COUNT(DISTINCT source_trade_id) unique_count "
                f"FROM `t_ods_event_{start:%Y%m}` "
                "WHERE event_time>=:start AND event_time<:end"
            ),
            {"start": start, "end": end},
        ).mappings().one()
    assert counts["row_count"] == counts["unique_count"]
