import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app


def auth_headers() -> dict[str, str]:
    token, _ = create_access_token(1, "admin")
    return {"Authorization": f"Bearer {token}"}


def test_entry_flow_report_returns_only_entry_directions() -> None:
    with TestClient(app, headers=auth_headers()) as client:
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
    assert body["total"] >= 8
    assert all(
        "入口" in item["direction_name"] or item["direction_id"] == 199 for item in body["items"]
    )


@pytest.mark.parametrize("granularity", ["day", "week", "month", "year"])
def test_entry_flow_report_supports_calendar_granularity(granularity: str) -> None:
    with TestClient(app, headers=auth_headers()) as client:
        response = client.get(
            "/api/v1/reports/entry-flow",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": granularity,
            },
        )

    assert response.status_code == 200
    assert response.json()["total"] >= 8


def test_exit_flow_report_returns_only_available_g50_directions() -> None:
    with TestClient(app, headers=auth_headers()) as client:
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
    assert all(
        "G50" in item["direction_name"] and "出口" in item["direction_name"]
        for item in response.json()["items"]
    )


def test_exit_direction_list_marks_non_g50_directions_unavailable() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        response = client.get("/api/v1/reports/directions", params={"flow": "exit"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 8
    assert all(
        item["availability"] == "AVAILABLE" for item in items if "G50" in item["direction_name"]
    )
    assert all(
        item["availability"] == "UNAVAILABLE"
        for item in items
        if "G50" not in item["direction_name"]
    )


def test_report_options_returns_all_dropdown_values() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        response = client.get("/api/v1/reports/options")

    assert response.status_code == 200
    body = response.json()
    assert len(body["entry_directions"]) == 9
    assert body["entry_directions"][-1] == {
        "direction_id": 199,
        "direction_name": "本路段收费站来源",
        "availability": "AVAILABLE",
    }
    assert len(body["exit_directions"]) == 8
    assert [item["station_name"] for item in body["local_entry_stations"]] == [
        "江苏汾湖站",
        "江苏北厍站",
        "江苏沪苏浙黎里站",
        "江苏平望站",
        "江苏横扇站",
        "江苏七都站",
    ]
    assert body["time_granularities"] == ["hour", "day", "week", "month", "year"]


def test_local_entry_station_flow_reports_each_station() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        response = client.get(
            "/api/v1/reports/local-entry-station-flow",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T16:00:00",
                "granularity": "hour",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert {item["station_name"] for item in body["items"]} == {
        "江苏汾湖站",
        "江苏北厍站",
        "江苏沪苏浙黎里站",
        "江苏平望站",
        "江苏横扇站",
        "江苏七都站",
    }


def test_vehicle_report_returns_type_code_and_paginates() -> None:
    with TestClient(app, headers=auth_headers()) as client:
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
    assert body["items"][0]["vehicle_type_name"] == "一型客车"


def test_media_vehicle_type_report_groups_by_media_type() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        directions = client.get("/api/v1/reports/directions", params={"flow": "entry"}).json()[
            "items"
        ]
        response = client.get(
            "/api/v1/reports/media-vehicle-types",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
                "direction_ids": directions[0]["direction_id"],
                "page_size": 500,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert all("入口" in item["direction_name"] for item in body["items"])
    assert all(item["media_type_name"] in {"OBU", "CPC", "无介质"} for item in body["items"])
    assert all("vehicle_type_name" in item for item in body["items"])


def test_media_vehicle_type_report_filters_media_and_vehicle_type() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        directions = client.get("/api/v1/reports/directions", params={"flow": "entry"}).json()[
            "items"
        ]
        response = client.get(
            "/api/v1/reports/media-vehicle-types",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
                "direction_ids": directions[0]["direction_id"],
                "vehicle_type_codes": "1",
                "media_type_codes": "2",
                "page_size": 500,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert {item["vehicle_type_code"] for item in body["items"]} == {"1"}
    assert {item["media_type_code"] for item in body["items"]} == {"2"}


def test_entry_station_report_marks_missing_name_as_unknown() -> None:
    with TestClient(app, headers=auth_headers()) as client:
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


def test_entry_province_report_returns_known_and_unknown_provinces() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        response = client.get(
            "/api/v1/reports/entry-provinces",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert all("入口" in item["direction_name"] for item in body["items"])
    assert any(item["province_code"] == "UNKNOWN" for item in body["items"])
    assert any(item["province_code"] != "UNKNOWN" for item in body["items"])


def test_entry_province_report_filters_by_direction_and_paginates() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        options = client.get("/api/v1/reports/directions", params={"flow": "entry"}).json()["items"]
        direction_id = options[0]["direction_id"]
        response = client.get(
            "/api/v1/reports/entry-provinces",
            params={
                "start": "2026-07-16T10:00:00",
                "end": "2026-07-16T11:00:00",
                "granularity": "hour",
                "direction_ids": direction_id,
                "page_size": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] > 0
    assert len(body["items"]) == 1
    assert body["items"][0]["direction_id"] == direction_id


def test_report_requires_login() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/reports/entry-flow")

    assert response.status_code == 401
