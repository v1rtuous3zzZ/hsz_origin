from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import create_access_token, verify_password
from app.db.dependencies import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    user = (
        db.execute(
            text(
                "SELECT user_id, username, password_hash, enabled, must_change_password, "
                "failed_login_count, locked_until FROM t_user WHERE username = :username"
            ),
            {"username": payload.username},
        )
        .mappings()
        .first()
    )
    now = datetime.now()
    invalid = (
        user is None
        or not user["enabled"]
        or (user["locked_until"] is not None and user["locked_until"] > now)
        or not verify_password(payload.password, user["password_hash"])
    )
    if invalid:
        if user is not None and user["enabled"]:
            failures = user["failed_login_count"] + 1
            locked_until = now + timedelta(minutes=15) if failures >= 5 else None
            db.execute(
                text(
                    "UPDATE t_user SET failed_login_count = :failures, locked_until = :locked_until "
                    "WHERE user_id = :user_id"
                ),
                {"failures": failures, "locked_until": locked_until, "user_id": user["user_id"]},
            )
            db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token, expires_in = create_access_token(user["user_id"], user["username"])
    db.execute(
        text(
            "UPDATE t_user SET failed_login_count = 0, locked_until = NULL, last_login_at = NOW(3), "
            "last_login_ip = :ip WHERE user_id = :user_id"
        ),
        {"ip": request.client.host if request.client else None, "user_id": user["user_id"]},
    )
    db.commit()
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "must_change_password": bool(user["must_change_password"]),
    }
