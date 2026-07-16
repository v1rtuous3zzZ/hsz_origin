from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def create_access_token(user_id: int, username: str) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.jwt_expire_minutes * 60
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    token = jwt.encode(
        {"sub": str(user_id), "username": username, "exp": expires_at},
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, expires_in
