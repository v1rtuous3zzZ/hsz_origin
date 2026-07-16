import argparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal


def upsert_user(db: Session, username: str, password: str, display_name: str) -> None:
    db.execute(
        text(
            "INSERT INTO t_user (username, password_hash, display_name, enabled, must_change_password, "
            "failed_login_count, locked_until) VALUES (:username, :password_hash, :display_name, 1, 1, 0, NULL) "
            "ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash), display_name = VALUES(display_name), "
            "enabled = 1, must_change_password = 1, failed_login_count = 0, locked_until = NULL"
        ),
        {"username": username, "password_hash": hash_password(password), "display_name": display_name},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="创建或重置本地登录账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", required=True)
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        upsert_user(db, args.username, args.password, args.display_name)


if __name__ == "__main__":
    main()
