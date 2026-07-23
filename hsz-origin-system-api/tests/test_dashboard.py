from fastapi.testclient import TestClient

from app.api.v1.dashboard import _actual_hours, _hour_map
from app.core.security import create_access_token
from app.main import app


def auth_headers() -> dict[str, str]:
    token, _ = create_access_token(1, "admin")
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_hours_only_include_synchronized_data() -> None:
    rows = [
        {"stat_hour": "2026-07-20 08:00:00", "group_key": "G50", "event_count": 12},
        {"stat_hour": "2026-07-20 10:00:00", "group_key": "G50", "event_count": 8},
    ]
    hours = _actual_hours(rows)

    assert [hour.hour for hour in hours] == [8, 10]
    assert _hour_map(rows, hours) == {"G50": [12, 8]}


def test_dashboard_endpoints_return_current_shapes() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        params = {"start": "2026-07-20T00:00:00", "end": "2026-07-21T00:00:00"}

        assert set(client.get("/api/v1/dashboard/latest-range").json()) == {
            "start",
            "end",
            "latest_hour",
        }
        assert set(client.get("/api/v1/dashboard/route-stack", params=params).json()) == {
            "times",
            "series",
        }
        assert set(client.get("/api/v1/dashboard/direction-flow", params=params).json()) == {
            "times",
            "routes",
        }
        assert set(client.get("/api/v1/dashboard/local-station-flow", params=params).json()) == {
            "times",
            "series",
        }
        assert set(client.get("/api/v1/dashboard/vehicle-type-ratio", params=params).json()) == {
            "items"
        }


def test_dashboard_section_rank_uses_physical_gantry_shape() -> None:
    with TestClient(app, headers=auth_headers()) as client:
        response = client.get(
            "/api/v1/dashboard/section-rank",
            params={"start": "2026-07-20T13:00:00", "end": "2026-07-20T14:00:00", "limit": 5},
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"totalCount", "items"}
    assert all(set(item) == {"name", "count"} for item in body["items"])


def test_dashboard_requires_login() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/dashboard/route-stack",
            params={"start": "2026-07-20T00:00:00", "end": "2026-07-21T00:00:00"},
        )

    assert response.status_code == 401
