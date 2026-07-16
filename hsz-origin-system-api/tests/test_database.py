from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app


def test_database_status() -> None:
    token, _ = create_access_token(1, "admin")
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        response = client.get("/api/v1/system/database")
    assert response.status_code == 200
    assert response.json()["database"] == "hsz_origin"
