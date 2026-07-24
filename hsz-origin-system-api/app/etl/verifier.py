from sqlalchemy import bindparam, text

from app.etl.chunks import chunked


def missing_trade_ids(source_ids: set[str], center_ids: set[str]) -> set[str]:
    return source_ids - center_ids


def center_trade_ids(db, source_ids: set[str], month: str, batch_size: int = 2000) -> set[str]:
    if not source_ids:
        return set()
    exists = db.execute(
        text(
            "SELECT 1 FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=:table"
        ),
        {"table": f"t_ods_event_{month}"},
    ).scalar_one_or_none()
    if not exists:
        return set()
    statement = text(
        f"SELECT trade_id FROM `t_ods_event_{month}` "
        "WHERE trade_id IN :trade_ids"
    ).bindparams(bindparam("trade_ids", expanding=True))
    found: set[str] = set()
    for values in chunked(list(source_ids), batch_size):
        found.update(str(value) for value in db.execute(statement, {"trade_ids": values}).scalars())
    return found
