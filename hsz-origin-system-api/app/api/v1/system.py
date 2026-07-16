import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.dependencies import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])


def database_unavailable(error: SQLAlchemyError) -> HTTPException:
    logger.warning("Database check failed: %s", error.__class__.__name__)
    return HTTPException(status_code=503, detail="数据库当前不可用")


@router.get("/database")
def database_status(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        version = db.execute(text("SELECT VERSION()")).scalar_one()
        database = db.execute(text("SELECT DATABASE()")).scalar_one()
    except SQLAlchemyError as error:
        raise database_unavailable(error) from error
    return {"status": "ok", "version": version, "database": database}


@router.get("/gantry-summary")
def gantry_summary(db: Session = Depends(get_db)) -> dict[str, int]:
    tables = {
        "source_server_count": "t_source_server",
        "physical_gantry_count": "t_physical_gantry",
        "logical_gantry_count": "t_logical_gantry",
        "active_mapping_count": "t_physical_logical_gantry_rel",
        "stat_object_count": "t_stat_object",
        "stat_rule_count": "t_stat_rule",
    }
    try:
        return {
            key: db.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE enabled = 1")
            ).scalar_one()
            for key, table in tables.items()
        }
    except SQLAlchemyError as error:
        raise database_unavailable(error) from error
