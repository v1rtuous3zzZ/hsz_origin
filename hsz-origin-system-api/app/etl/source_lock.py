from contextlib import contextmanager

from sqlalchemy import text

from app.db.engine import engine


SOURCE_READ_LOCK_NAME = "hsz:etl:source-read"


@contextmanager
def source_read_lock(timeout_seconds: int, enabled: bool = True):
    """仅串行化门架读取阶段；中心库处理不占用该锁。"""
    if not enabled:
        yield
        return

    with engine.connect() as connection:
        acquired = connection.execute(
            text("SELECT GET_LOCK(:name, :timeout)"),
            {"name": SOURCE_READ_LOCK_NAME, "timeout": timeout_seconds},
        ).scalar_one()
        if acquired != 1:
            raise RuntimeError("等待门架读取锁超时，当前可能已有实时或历史同步在读取源库")
        try:
            yield
        finally:
            connection.execute(
                text("SELECT RELEASE_LOCK(:name)"), {"name": SOURCE_READ_LOCK_NAME}
            )
