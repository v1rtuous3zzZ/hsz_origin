from fastapi.testclient import TestClient

from app.main import app


def test_database_status() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/database")
    assert response.status_code == 200
    assert response.json()["database"] == "hsz_origin"
