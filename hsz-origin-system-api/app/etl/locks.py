from contextlib import contextmanager

from sqlalchemy import text

from app.db.engine import engine


def lock_name(job_type: str, source_mode: str = "remote", job_name: str | None = None) -> str:
    return (
        f"hsz:etl:backfill:{job_name}" if job_type == "backfill" else f"hsz:etl:live:{source_mode}"
    )


@contextmanager
def mysql_lock(name: str):
    with engine.connect() as connection:
        if connection.execute(text("SELECT GET_LOCK(:name, 0)"), {"name": name}).scalar_one() != 1:
            raise RuntimeError(f"无法获取 ETL 锁：{name}")
        try:
            yield
        finally:
            connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": name})
