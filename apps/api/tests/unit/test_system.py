from typing import Any

import httpx
import pytest

from gridwise_api.config import Settings
from gridwise_api.main import create_app


async def test_system_info_states_the_safety_boundary(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/system/info")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "gridwise-api"
    assert body["environment"] == "test"
    assert body["operating_mode"] == "simulation_and_decision_support"
    assert "does not issue switching commands" in body["notice"]


async def test_cors_allows_only_configured_origins(client: httpx.AsyncClient) -> None:
    allowed = await client.get("/health/live", headers={"Origin": "http://localhost:3100"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3100"
    denied = await client.get("/health/live", headers={"Origin": "http://evil.example.test"})
    assert "access-control-allow-origin" not in denied.headers


# Every route and method the API exposes. A new one must be added here on purpose: this is
# the safety boundary's explicit allow-list (docs/security/safety-boundary.md). None of
# these reaches any equipment; the writes change stored simulation data only.
READ_ONLY_ROUTES = {
    ("/health/live", "get"),
    ("/health/ready", "get"),
    ("/api/v1/system/info", "get"),
}
GRID_ROUTES = {
    ("/api/v1/grids", "get"),
    ("/api/v1/grids", "post"),
    ("/api/v1/grids/{grid_id}", "get"),
    ("/api/v1/grids/{grid_id}", "patch"),
    ("/api/v1/grids/{grid_id}", "delete"),
    ("/api/v1/grids/{grid_id}/topology", "get"),
    ("/api/v1/grids/{grid_id}/topology", "put"),
    ("/api/v1/grids/{grid_id}/assets/{asset_type}", "get"),
    ("/api/v1/grids/{grid_id}/assets/{asset_type}/{key}", "get"),
    ("/api/v1/grids/{grid_id}/assets/{asset_type}/{key}", "patch"),
}
# Scenarios and simulations (decision 0013). Writes store scenarios and queued jobs, or
# cancel a queued job; nothing runs a power flow in a request, and nothing reaches equipment.
SIMULATION_ROUTES = {
    ("/api/v1/scenarios", "get"),
    ("/api/v1/scenarios", "post"),
    ("/api/v1/scenarios/{scenario_id}", "get"),
    ("/api/v1/scenarios/{scenario_id}", "delete"),
    ("/api/v1/grids/{grid_id}/simulations", "post"),
    ("/api/v1/simulations", "get"),
    ("/api/v1/simulations/{job_id}", "get"),
    ("/api/v1/simulations/{job_id}/cancel", "post"),
    ("/api/v1/simulations/{job_id}/result", "get"),
    ("/api/v1/simulations/{job_id}/reproductions", "get"),
}
DEVELOPMENT_ROUTES = GRID_ROUTES | SIMULATION_ROUTES


def _routes(schema: dict[str, Any]) -> set[tuple[str, str]]:
    return {(path, method) for path, item in schema["paths"].items() for method in item}


async def test_the_api_exposes_exactly_the_allowed_routes(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert _routes(schema) == READ_ONLY_ROUTES | DEVELOPMENT_ROUTES


async def test_platform_endpoints_stay_read_only(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    writes = {(path, method) for path, method in _routes(schema) if method != "get"}
    assert writes
    assert writes <= DEVELOPMENT_ROUTES
    assert not any(path in {p for p, _ in READ_ONLY_ROUTES} for path, _ in writes)


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_outside_development_only_the_read_only_routes_exist(environment: str) -> None:
    """The grid, scenario and simulation APIs act for the development tenant, so they do
    not exist elsewhere."""
    settings = Settings(
        _env_file=None,
        environment=environment,
        log_format="json",
        database_url="postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        schema = (await client.get("/openapi.json")).json()
        assert _routes(schema) == READ_ONLY_ROUTES
        some_id = "00000000-0000-4000-8000-000000000000"
        for path in (
            "/api/v1/grids",
            f"/api/v1/grids/{some_id}",
            "/api/v1/scenarios",
            "/api/v1/simulations",
            f"/api/v1/simulations/{some_id}",
            f"/api/v1/simulations/{some_id}/result",
            f"/api/v1/simulations/{some_id}/reproductions",
        ):
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"
        for path in (
            "/api/v1/grids",
            "/api/v1/scenarios",
            f"/api/v1/grids/{some_id}/simulations",
            f"/api/v1/simulations/{some_id}/cancel",
        ):
            response = await client.post(path, json={})
            assert response.status_code == 404


async def test_cors_allows_writes_from_configured_origins_only(client: httpx.AsyncClient) -> None:
    preflight = {
        "Origin": "http://localhost:3100",
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "if-match, content-type",
    }
    allowed = await client.options("/api/v1/grids/x", headers=preflight)
    assert allowed.status_code == 200
    assert "PATCH" in allowed.headers["access-control-allow-methods"]
    assert "if-match" in allowed.headers["access-control-allow-headers"].lower()

    denied = await client.options(
        "/api/v1/grids/x", headers={**preflight, "Origin": "http://evil.example.test"}
    )
    assert "access-control-allow-origin" not in denied.headers

    exposed = await client.get("/health/live", headers={"Origin": "http://localhost:3100"})
    assert "etag" in exposed.headers["access-control-expose-headers"].lower()


async def test_cors_allows_the_idempotency_headers(client: httpx.AsyncClient) -> None:
    preflight = {
        "Origin": "http://localhost:3100",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "idempotency-key, if-match, content-type",
    }
    allowed = await client.options("/api/v1/grids/x/simulations", headers=preflight)
    assert allowed.status_code == 200
    assert "idempotency-key" in allowed.headers["access-control-allow-headers"].lower()
    exposed = await client.get("/health/live", headers={"Origin": "http://localhost:3100"})
    exposed_headers = exposed.headers["access-control-expose-headers"].lower()
    assert {"location", "idempotent-replayed"} <= set(exposed_headers.replace(" ", "").split(","))
