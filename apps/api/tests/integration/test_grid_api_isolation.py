"""Tenant isolation through HTTP, and where the grid API exists at all.

Two apps act for two organisations against one database. Neither can see, change or learn
anything about the other's grids: every attempt gets the same 404 a random id gets, and
changes nothing.

This shows that the API keeps tenants apart once it knows which tenant it acts for. It does
not show who may act for which tenant: there is no authentication yet, and the tenant is
the fixed development tenant chosen by the server's configuration.
"""

import uuid

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api import seed
from gridwise_grid_engine import grid_hash
from gridwise_grid_engine.reference_grids import cigre_mv
from tests.integration.conftest import TestDatabase
from tests.support.api import (
    create_payload,
    database_snapshot,
    grid_api,
    topology_payload,
    without_request_id,
)
from tests.support.grids import GRID_TABLES, SAMPLE_COORDINATES, sample_grid

pytestmark = pytest.mark.integration


@pytest.fixture
async def alpha_grid(alpha_api: httpx.AsyncClient) -> str:
    response = await alpha_api.post(
        "/api/v1/grids", json=create_payload(sample_grid(), SAMPLE_COORDINATES)
    )
    assert response.status_code == 201
    return str(response.json()["id"])


type Spec = tuple[object, dict[str, str]] | None


def _requests(grid_id: str) -> list[tuple[str, str, Spec]]:
    write = {"If-Match": '"1"'}
    return [
        ("GET", f"/api/v1/grids/{grid_id}", None),
        ("GET", f"/api/v1/grids/{grid_id}/topology", None),
        ("GET", f"/api/v1/grids/{grid_id}/assets/buses", None),
        ("GET", f"/api/v1/grids/{grid_id}/assets/buses/a", None),
        ("PATCH", f"/api/v1/grids/{grid_id}", ({"description": "mine now"}, write)),
        ("PUT", f"/api/v1/grids/{grid_id}/topology", (topology_payload(sample_grid()), write)),
        ("PATCH", f"/api/v1/grids/{grid_id}/assets/switches/s-bc", ({"closed": True}, write)),
        ("DELETE", f"/api/v1/grids/{grid_id}", (None, write)),
    ]


async def _send(client: httpx.AsyncClient, method: str, url: str, spec: Spec) -> httpx.Response:
    if spec is None:
        return await client.request(method, url)
    body, headers = spec
    return await client.request(method, url, json=body, headers=headers)


@pytest.mark.parametrize("index", range(8))
async def test_another_tenants_grid_is_indistinguishable_from_a_missing_one(
    alpha_grid: str, bravo_api: httpx.AsyncClient, owner_engine: Engine, index: int
) -> None:
    before = database_snapshot(owner_engine)
    method, url, spec = _requests(alpha_grid)[index]
    foreign = await _send(bravo_api, method, url, spec)

    _, random_url, _ = _requests(str(uuid.uuid4()))[index]
    missing = await _send(bravo_api, method, random_url, spec)

    assert foreign.status_code == missing.status_code == 404
    assert without_request_id(foreign.json()) == without_request_id(missing.json())
    assert foreign.json()["error"]["code"] == "grid_not_found"
    assert "etag" not in foreign.headers
    assert alpha_grid not in foreign.text
    assert database_snapshot(owner_engine) == before


async def test_a_stale_if_match_on_another_tenants_grid_is_still_404(
    alpha_grid: str, bravo_api: httpx.AsyncClient
) -> None:
    """A 412 would confirm the grid exists and reveal its version."""
    for version in ('"1"', '"2"', '"99"'):
        response = await bravo_api.patch(
            f"/api/v1/grids/{alpha_grid}", json={"description": "x"}, headers={"If-Match": version}
        )
        assert response.status_code == 404
        assert "etag" not in response.headers


async def test_each_tenant_lists_only_its_own_grids(
    alpha_api: httpx.AsyncClient, bravo_api: httpx.AsyncClient, alpha_grid: str
) -> None:
    created = await bravo_api.post(
        "/api/v1/grids", json=create_payload(sample_grid("Bravo feeder (synthetic)"))
    )
    bravo_grid = created.json()["id"]

    alpha_list = (await alpha_api.get("/api/v1/grids")).json()
    bravo_list = (await bravo_api.get("/api/v1/grids")).json()
    assert [item["id"] for item in alpha_list["items"]] == [alpha_grid]
    assert [item["id"] for item in bravo_list["items"]] == [bravo_grid]
    assert alpha_list["total"] == bravo_list["total"] == 1


async def test_no_response_carries_organisation_or_element_row_ids(
    alpha_api: httpx.AsyncClient,
    alpha_grid: str,
    tenants: dict[str, uuid.UUID],
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        row_ids = {
            str(row_id)
            for table in GRID_TABLES[1:]
            for row_id in connection.execute(text(f"SELECT id FROM grid.{table}")).scalars()  # noqa: S608
        }
    assert row_ids
    secrets = row_ids | {str(organization) for organization in tenants.values()}

    bodies = [
        (await alpha_api.get(url)).text
        for url in (
            "/api/v1/grids",
            f"/api/v1/grids/{alpha_grid}",
            f"/api/v1/grids/{alpha_grid}/topology",
            *(f"/api/v1/grids/{alpha_grid}/assets/{table}" for table in GRID_TABLES[1:]),
            f"/api/v1/grids/{alpha_grid}/assets/buses/a",
        )
    ]
    patched = await alpha_api.patch(
        f"/api/v1/grids/{alpha_grid}/assets/lines/ab",
        json={"in_service": False},
        headers={"If-Match": '"1"'},
    )
    bodies.append(patched.text)
    for body in bodies:
        assert not any(secret in body for secret in secrets)


async def test_the_same_key_in_two_tenants_grids_stays_apart(
    alpha_api: httpx.AsyncClient, bravo_api: httpx.AsyncClient, alpha_grid: str
) -> None:
    bravo_grid = (await bravo_api.post("/api/v1/grids", json=create_payload(sample_grid()))).json()[
        "id"
    ]
    await bravo_api.patch(
        f"/api/v1/grids/{bravo_grid}/assets/buses/a",
        json={"name": "Bravo's A"},
        headers={"If-Match": '"1"'},
    )
    alpha_bus = (await alpha_api.get(f"/api/v1/grids/{alpha_grid}/assets/buses/a")).json()
    assert alpha_bus["asset"]["name"] == "A"
    assert alpha_bus["grid_version"] == 1


# --- where the API exists -----------------------------------------------------------------


@pytest.mark.parametrize("environment", ["staging", "production"])
async def test_the_grid_api_does_not_exist_outside_development(
    database: TestDatabase, alpha_grid: str, environment: str
) -> None:
    async with grid_api(database.app_url, None, environment=environment) as client:
        for method, url, spec in _requests(alpha_grid):
            response = await _send(client, method, url, spec)
            assert response.status_code == 404, (method, url)
            assert response.json()["error"]["code"] == "not_found"
        assert (await client.get("/api/v1/grids")).status_code == 404


async def test_without_a_development_tenant_the_grid_api_answers_503(
    database: TestDatabase, alpha_grid: str, owner_engine: Engine
) -> None:
    before = database_snapshot(owner_engine)
    async with grid_api(database.app_url, None, environment="local") as client:
        for method, url, spec in [("GET", "/api/v1/grids", None), *_requests(alpha_grid)]:
            response = await _send(client, method, url, spec)
            assert response.status_code == 503, (method, url)
            assert response.json()["error"]["code"] == "development_tenant_not_configured"
            assert alpha_grid not in response.text
    assert database_snapshot(owner_engine) == before


async def test_without_a_development_tenant_no_database_query_is_made() -> None:
    """The database URL points nowhere: a query would fail differently from the 503."""
    async with grid_api(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", None, environment="test"
    ) as client:
        response = await client.get("/api/v1/grids")
    assert response.status_code == 503


# --- the seeded demonstration grid --------------------------------------------------------


async def test_the_seeded_demonstration_grid_is_readable_through_the_api(
    migrated: None, owner_async_engine: AsyncEngine, database: TestDatabase
) -> None:
    await seed.seed_demo(owner_async_engine, environment="test")
    async with grid_api(database.app_url, seed.DEV_ORGANIZATION_ID) as client:
        listing = (await client.get("/api/v1/grids")).json()
        assert [item["id"] for item in listing["items"]] == [str(seed.DEMO_GRID_ID)]
        grid = listing["items"][0]
        assert grid["data_origin"] == "synthetic"
        assert "synthetic" in grid["name"].lower()
        assert grid["topology_hash"] == grid_hash(cigre_mv.cigre_mv_with_der())

        topology = (await client.get(f"/api/v1/grids/{seed.DEMO_GRID_ID}/topology")).json()
        buses = {bus["key"]: bus for bus in topology["topology"]["buses"]}
        assert buses["bus-3"]["diagram"] == {
            "x": cigre_mv.BUS_DIAGRAM_COORDINATES["bus-3"][0],
            "y": cigre_mv.BUS_DIAGRAM_COORDINATES["bus-3"][1],
        }
        assert sum(not switch["closed"] for switch in topology["topology"]["switches"]) == 3
