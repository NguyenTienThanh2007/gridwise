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


def _routes(schema: dict[str, Any]) -> set[tuple[str, str]]:
    return {(path, method) for path, item in schema["paths"].items() for method in item}


async def test_the_api_exposes_exactly_the_allowed_routes(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert _routes(schema) == READ_ONLY_ROUTES | GRID_ROUTES


async def test_platform_endpoints_stay_read_only(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    writes = {(path, method) for path, method in _routes(schema) if method != "get"}
    assert writes
    assert all(path.startswith("/api/v1/grids") for path, _ in writes)


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_outside_development_only_the_read_only_routes_exist(environment: str) -> None:
    """The grid API acts for the development tenant, so it does not exist elsewhere."""
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
        for path in ("/api/v1/grids", "/api/v1/grids/00000000-0000-4000-8000-000000000000"):
            response = await client.get(path)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"
        response = await client.post("/api/v1/grids", json={})
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
