import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_entry_flow_report_returns_only_entry_directions() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/reports/entry-flow",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 8
    assert all("进入本路段" in item["direction_name"] for item in body["items"])


@pytest.mark.parametrize("granularity", ["day", "week", "month", "year"])
def test_entry_flow_report_supports_calendar_granularity(granularity: str) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/reports/entry-flow",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": granularity,
            },
        )

    assert response.status_code == 200
    assert response.json()["total"] == 8


def test_exit_flow_report_returns_only_available_g50_directions() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/reports/exit-flow",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
            },
        )

    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert all("G50" in item["direction_name"] for item in response.json()["items"])


def test_exit_direction_list_marks_non_g50_directions_unavailable() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/reports/directions", params={"flow": "exit"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 8
    assert all(item["availability"] == "AVAILABLE" for item in items if "G50" in item["direction_name"])
    assert all(item["availability"] == "UNAVAILABLE" for item in items if "G50" not in item["direction_name"])


def test_vehicle_report_returns_type_code_and_paginates() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/reports/vehicle-types",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
                "page_size": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 1
    assert len(body["items"]) == 1
    assert body["items"][0]["vehicle_type_code"] == "1"


def test_entry_station_report_marks_missing_name_as_unknown() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/reports/entry-stations",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
                "page": 2,
                "page_size": 500,
            },
        )

    assert response.status_code == 200
    assert any(item["station_name"] == "\u672a\u77e5" for item in response.json()["items"])
