from sqlalchemy import text
from sqlalchemy.orm import Session

from app.etl.models import Rule, SourceServer


def load_sources(db: Session, server_code: str | None = None) -> list[SourceServer]:
    rows = db.execute(
        text(
            "SELECT source_server_id, server_code, host_address, host_port, database_name, current_table_name, monthly_table_pattern, credential_key FROM t_source_server WHERE enabled=1 AND host_address LIKE '10.13.%' AND (:code IS NULL OR server_code=:code) ORDER BY read_priority, source_server_id"
        ),
        {"code": server_code},
    ).mappings()
    return [SourceServer(**row) for row in rows]


def load_mapping(db: Session) -> dict[int, dict[str, str]]:
    rows = db.execute(
        text(
            "SELECT p.source_server_id, p.physical_gantry_code, r.logical_gantry_hex FROM t_physical_gantry p JOIN t_source_server s ON s.source_server_id=p.source_server_id JOIN t_legacy_gantry_info legacy ON legacy.gantry_id=p.physical_gantry_code JOIN t_physical_logical_gantry_rel r ON r.physical_gantry_id=p.physical_gantry_id WHERE p.enabled=1 AND s.enabled=1 AND s.host_address LIKE '10.13.%' AND r.enabled=1 AND r.valid_from<=NOW(3) AND (r.valid_to IS NULL OR r.valid_to>NOW(3))"
        )
    ).mappings()
    result: dict[int, dict[str, str]] = {}
    for row in rows:
        result.setdefault(row["source_server_id"], {})[row["physical_gantry_code"]] = row[
            "logical_gantry_hex"
        ]
    return result


def load_rules(db: Session) -> list[Rule]:
    rows = db.execute(
        text(
            "SELECT rule_no, object_no, rule_type, previous_gantry_hex, current_gantry_hex, valid_from, valid_to FROM t_stat_rule WHERE enabled=1"
        )
    ).mappings()
    return [Rule(**row) for row in rows]
