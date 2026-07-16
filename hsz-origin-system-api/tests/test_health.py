from fastapi.testclient import TestClient

from app.main import app


def test_health_does_not_need_database() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
