from fastapi.testclient import TestClient

from app.main import app


def test_login_rejects_invalid_credentials() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "not-a-user", "password": "incorrect"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "用户名或密码错误"}
