from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.v1.etl import missing_windows, two_hour_windows
from app.core.security import create_access_token
from app.etl.reconcile import completed_windows
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
        response = client.get(
            "/api/v1/etl/batches", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert "items" in response.json()


def test_manual_sync_uses_resumable_history_loop_by_default() -> None:
    token, _ = create_access_token(1, "admin")
    expected = {"status": "SUCCESS", "window_count": 1, "batches": []}
    with (
        TestClient(app) as client,
        patch("app.api.v1.etl.sync_range", return_value=expected) as sync,
    ):
        response = client.post(
            "/api/v1/etl/manual-sync",
            headers={"Authorization": f"Bearer {token}"},
            json={"start": "2026-07-01T00:00:00", "end": "2026-07-01T02:00:00"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    sync.assert_called_once_with(
        datetime(2026, 7, 1),
        datetime(2026, 7, 1, 2),
        window_minutes=120,
        sleep_seconds=1,
        resume=True,
        continue_on_error=True,
        rebuild_facts=False,
    )


def test_manual_sync_can_rebuild_facts_after_all_windows() -> None:
    token, _ = create_access_token(1, "admin")
    with (
        TestClient(app) as client,
        patch(
            "app.api.v1.etl.sync_range",
            return_value={"status": "SUCCESS", "window_count": 1, "batches": []},
        ) as sync,
    ):
        response = client.post(
            "/api/v1/etl/manual-sync",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "start": "2026-07-01T00:00:00",
                "end": "2026-07-01T02:00:00",
                "rebuild_facts": True,
                "sleep_seconds": 0,
            },
        )

    assert response.status_code == 200
    sync.assert_called_once_with(
        datetime(2026, 7, 1),
        datetime(2026, 7, 1, 2),
        window_minutes=120,
        sleep_seconds=0,
        resume=True,
        continue_on_error=True,
        rebuild_facts=True,
    )


def test_missing_windows_reports_only_uncovered_windows() -> None:
    start = datetime(2026, 7, 1, 8)
    end = datetime(2026, 7, 1, 14)

    assert missing_windows(
        start,
        end,
        [
            (datetime(2026, 7, 1, 8), datetime(2026, 7, 1, 10)),
            (datetime(2026, 7, 1, 12), datetime(2026, 7, 1, 14)),
        ],
    ) == [{"start": datetime(2026, 7, 1, 10), "end": datetime(2026, 7, 1, 12)}]


def test_nightly_reconcile_uses_completed_two_hour_windows_only() -> None:
    windows = list(completed_windows(datetime(2026, 7, 19, 4, 15), lookback_days=1))

    assert windows[0] == (datetime(2026, 7, 18), datetime(2026, 7, 18, 2))
    assert windows[-1] == (datetime(2026, 7, 18, 22), datetime(2026, 7, 19))
    assert len(windows) == 12
