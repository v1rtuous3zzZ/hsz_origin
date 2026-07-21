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


def test_manual_sync_is_queued_and_returns_immediately() -> None:
    token, _ = create_access_token(1, "admin")
    queued = {
        "job_id": 12,
        "job_no": "MANUAL-test",
        "status": "PENDING",
        "window_start": datetime(2026, 7, 1),
        "window_end": datetime(2026, 7, 1, 2),
    }
    with (
        TestClient(app) as client,
        patch("app.api.v1.etl.enqueue_manual_sync", return_value=queued) as enqueue,
    ):
        response = client.post(
            "/api/v1/etl/manual-sync",
            headers={"Authorization": f"Bearer {token}"},
            json={"start": "2026-07-01T00:00:00", "end": "2026-07-01T02:00:00"},
        )

    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert response.json()["status_url"] == "/api/v1/etl/manual-sync-jobs/12"
    enqueue.assert_called_once()
    kwargs = enqueue.call_args.kwargs
    assert kwargs["start"] == datetime(2026, 7, 1)
    assert kwargs["end"] == datetime(2026, 7, 1, 2)
    assert kwargs["window_minutes"] == 120
    assert kwargs["rebuild_facts"] is False


def test_manual_sync_can_queue_fact_rebuild() -> None:
    token, _ = create_access_token(1, "admin")
    queued = {
        "job_id": 13,
        "job_no": "MANUAL-facts",
        "status": "PENDING",
        "window_start": datetime(2026, 7, 1),
        "window_end": datetime(2026, 7, 1, 2),
    }
    with (
        TestClient(app) as client,
        patch("app.api.v1.etl.enqueue_manual_sync", return_value=queued) as enqueue,
    ):
        response = client.post(
            "/api/v1/etl/manual-sync",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "start": "2026-07-01T00:00:00",
                "end": "2026-07-01T02:00:00",
                "rebuild_facts": True,
            },
        )

    assert response.status_code == 202
    assert enqueue.call_args.kwargs["rebuild_facts"] is True


def test_manual_sync_job_status_endpoint() -> None:
    token, _ = create_access_token(1, "admin")
    with (
        TestClient(app) as client,
        patch(
            "app.api.v1.etl.get_manual_job",
            return_value={"job_id": 12, "status": "RUNNING"},
        ),
    ):
        response = client.get(
            "/api/v1/etl/manual-sync-jobs/12",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"job_id": 12, "status": "RUNNING"}


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
