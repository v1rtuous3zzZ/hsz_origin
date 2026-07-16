import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.admin import upsert_user
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app


def test_login_rejects_invalid_credentials() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "not-a-user", "password": "incorrect"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "用户名或密码错误"}


def test_login_returns_a_token_for_initialized_user() -> None:
    username = "login-test-user"
    password = "login-test-password"
    with SessionLocal.begin() as db:
        upsert_user(db, username, password, "Login test user")
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/login", json={"username": username, "password": password})

        assert response.status_code == 200
        body = response.json()
        claims = jwt.decode(body["access_token"], get_settings().jwt_secret, algorithms=["HS256"])
        assert claims["username"] == username
        assert body["token_type"] == "bearer"
        assert body["must_change_password"] is True
    finally:
        with SessionLocal.begin() as db:
            db.execute(text("DELETE FROM t_user WHERE username = :username"), {"username": username})
