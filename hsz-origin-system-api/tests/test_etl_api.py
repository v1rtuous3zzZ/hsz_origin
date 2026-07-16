from datetime import datetime

from fastapi.testclient import TestClient

from app.api.v1.etl import two_hour_windows
from app.core.security import create_access_token
from app.main import app


def test_manual_sync_windows_are_two_hours_and_do_not_cross_month() -> None:
    windows = list(two_hour_windows(datetime(2026, 7, 31, 22), datetime(2026, 8, 1, 3)))
    assert windows == [
        (datetime(2026, 7, 31, 22), datetime(2026, 8, 1)),
        (datetime(2026, 8, 1), datetime(2026, 8, 1, 2)),
        (datetime(2026, 8, 1, 2), datetime(2026, 8, 1, 3)),
    ]


def test_batch_log_api_requires_login() -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/etl/batches").status_code == 401
        token, _ = create_access_token(1, "admin")
        response = client.get("/api/v1/etl/batches", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert "items" in response.json()
