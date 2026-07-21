"""Replace copied legacy metadata with HSZ Origin business configuration."""

import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal

LOCAL_ENTRY_STATIONS = [
    ("32012802", 10),
    ("32012803", 20),
    ("32012804", 30),
    ("32012805", 40),
    ("32012806", 50),
    ("32012807", 60),
]

LOCAL_ENTRY_FACT_TABLES = [
    ("hourly", "stat_hour DATETIME NOT NULL COMMENT '统计小时，精确到整点'", "stat_hour"),
    ("daily", "stat_date DATE NOT NULL COMMENT '统计日期'", "stat_date"),
    ("monthly", "stat_month DATE NOT NULL COMMENT '统计月份，固定为每月1日'", "stat_month"),
]


def has_table(db, name: str) -> bool:
    return db.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema=DATABASE() AND table_name=:name"
        ),
        {"name": name},
    ).scalar_one() == 1


def has_column(db, table: str, column: str) -> bool:
    return db.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema=DATABASE() AND table_name=:table AND column_name=:column"
        ),
        {"table": table, "column": column},
    ).scalar_one() == 1


def main() -> None:
    with SessionLocal.begin() as db:
        if not has_column(db, "t_physical_gantry", "collection_enabled"):
            db.execute(
                text(
                    "ALTER TABLE t_physical_gantry ADD COLUMN collection_enabled "
                    "TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '是否纳入本项目正式门架采集范围：1是，0否' AFTER enabled"
                )
            )
        if has_table(db, "t_legacy_gantry_info"):
            db.execute(
                text(
                    "UPDATE t_physical_gantry p JOIN t_legacy_gantry_info l "
                    "ON l.gantry_id=p.physical_gantry_code "
                    "SET p.collection_enabled=1 WHERE p.enabled=1"
                )
            )

        if not has_table(db, "t_local_entry_station"):
            db.execute(
                text(
                    "CREATE TABLE t_local_entry_station ("
                    "local_entry_station_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '本路段入口收费站主键',"
                    "toll_station_id BIGINT UNSIGNED NOT NULL COMMENT '收费站主键',"
                    "sort_no SMALLINT UNSIGNED NOT NULL COMMENT '本路段收费站展示顺序',"
                    "enabled TINYINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '是否纳入本路段收费站来源统计：1是，0否',"
                    "created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',"
                    "updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '最后更新时间',"
                    "PRIMARY KEY (local_entry_station_id),"
                    "UNIQUE KEY uk_local_entry_station_toll_station (toll_station_id),"
                    "KEY idx_local_entry_station_enabled_sort (enabled, sort_no),"
                    "CONSTRAINT fk_local_entry_station_toll_station FOREIGN KEY (toll_station_id) "
                    "REFERENCES t_toll_station(toll_station_id)"
                    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='本路段入口收费站范围，用于统计本路段收费站来源车辆'"
                )
            )
        for station_code, sort_no in LOCAL_ENTRY_STATIONS:
            db.execute(
                text(
                    "INSERT INTO t_local_entry_station (toll_station_id,sort_no) "
                    "SELECT toll_station_id,:sort_no FROM t_toll_station WHERE station_code=:station_code "
                    "ON DUPLICATE KEY UPDATE sort_no=VALUES(sort_no),enabled=1"
                ),
                {"station_code": station_code, "sort_no": sort_no},
            )

        for grain, period_column, index_column in LOCAL_ENTRY_FACT_TABLES:
            db.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS t_fact_local_entry_flow_{grain} ("
                    f"{period_column},"
                    "event_count BIGINT UNSIGNED NOT NULL COMMENT '本路段收费站来源车辆数，按事件去重',"
                    "last_batch_id BIGINT UNSIGNED NULL COMMENT '最后重建该事实的同步批次主键',"
                    "updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '最后更新时间',"
                    f"PRIMARY KEY ({index_column}),"
                    f"CONSTRAINT ck_local_entry_flow_{grain}_event_count CHECK (event_count >= 0)"
                    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='本路段收费站来源入口流量事实表'"
                )
            )
            db.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS t_fact_local_entry_station_flow_{grain} ("
                    f"{period_column},"
                    "toll_station_id BIGINT UNSIGNED NOT NULL COMMENT '本路段入口收费站主键',"
                    "event_count BIGINT UNSIGNED NOT NULL COMMENT '本路段收费站来源车辆数，按事件去重',"
                    "last_batch_id BIGINT UNSIGNED NULL COMMENT '最后重建该事实的同步批次主键',"
                    "updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '最后更新时间',"
                    f"PRIMARY KEY ({index_column}, toll_station_id),"
                    "KEY idx_local_entry_station_flow_station (toll_station_id),"
                    f"CONSTRAINT ck_local_entry_station_flow_{grain}_event_count CHECK (event_count >= 0),"
                    f"CONSTRAINT fk_local_entry_station_flow_{grain}_station FOREIGN KEY (toll_station_id) "
                    "REFERENCES t_toll_station(toll_station_id)"
                    ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='本路段收费站来源入口流量事实表'"
                )
            )

        if has_table(db, "t_network_entry_station_rel"):
            db.execute(text("DROP TABLE t_network_entry_station_rel"))

        for table in ("t_base_facility_catalog", "t_base_gantry_catalog", "t_legacy_gantry_info"):
            if has_table(db, table):
                db.execute(text(f"DROP TABLE {table}"))

        remark_tables = db.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema=DATABASE() AND column_name='remark'"
            )
        ).scalars()
        for table in remark_tables:
            db.execute(text(f"ALTER TABLE `{table}` DROP COLUMN remark"))


if __name__ == "__main__":
    main()
