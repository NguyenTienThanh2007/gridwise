import httpx


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


async def test_no_write_endpoints_exist_in_p0(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    methods = {method for path in schema["paths"].values() for method in path}
    assert methods == {"get"}
