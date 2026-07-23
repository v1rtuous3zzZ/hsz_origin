"""Rebuild local-entry source flow facts from existing monthly match tables."""

import re
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal


def main() -> None:
    with SessionLocal.begin() as db:
        tables = db.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND table_name LIKE 't_event_object_match_%'"
            )
        ).scalars()
        match_tables = [table for table in tables if re.fullmatch(r"t_event_object_match_\d{6}", table)]

        for grain in ("hourly", "daily", "monthly"):
            db.execute(text(f"DELETE FROM t_fact_local_entry_flow_{grain}"))
            db.execute(text(f"DELETE FROM t_fact_local_entry_station_flow_{grain}"))

        for match_table in match_tables:
            for grain, period in (
                ("hourly", "DATE_FORMAT(m.event_time,'%Y-%m-%d %H:00:00')"),
                ("daily", "DATE(m.event_time)"),
                ("monthly", "DATE_FORMAT(m.event_time,'%Y-%m-01')"),
            ):
                key = {"hourly": "stat_hour", "daily": "stat_date", "monthly": "stat_month"}[grain]
                db.execute(
                    text(
                        f"INSERT INTO t_fact_local_entry_flow_{grain} ({key},event_count) "
                        f"SELECT {period},COUNT(DISTINCT m.trade_id) FROM `{match_table}` m "
                        "JOIN t_toll_station s ON s.station_code=m.entry_station_code "
                        "JOIN t_local_entry_station l ON l.toll_station_id=s.toll_station_id AND l.enabled=1 "
                        f"GROUP BY {period}"
                    )
                )
                db.execute(
                    text(
                        f"INSERT INTO t_fact_local_entry_station_flow_{grain} ({key},toll_station_id,event_count) "
                        f"SELECT {period},s.toll_station_id,COUNT(DISTINCT m.trade_id) FROM `{match_table}` m "
                        "JOIN t_toll_station s ON s.station_code=m.entry_station_code "
                        "JOIN t_local_entry_station l ON l.toll_station_id=s.toll_station_id AND l.enabled=1 "
                        f"GROUP BY {period},s.toll_station_id"
                    )
                )


if __name__ == "__main__":
    main()
