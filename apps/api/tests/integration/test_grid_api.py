"""The grid API over HTTP: create, read, change and delete grids, topologies and assets.

Every test goes through the app as deployed: HTTP, the runtime role, a real database. After
each write the stored hash is checked against the model rebuilt from the database rows.
"""

import uuid
from dataclasses import replace

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine import grid_hash
from gridwise_grid_engine.reference_grids import cigre_mv
from tests.support.api import create_payload, topology_payload
from tests.support.grids import SAMPLE_COORDINATES, plain_grid, sample_grid

pytestmark = pytest.mark.integration


async def _stored_hash(
    engine: AsyncEngine, organization_id: uuid.UUID, grid_id: str
) -> tuple[str, str]:
    """(stored topology_hash, grid_hash of the model rebuilt from the rows)."""
    async with tenant_transaction(engine, organization_id) as session:
        stored = await grids.load_grid(session, uuid.UUID(grid_id))
    assert stored is not None
    return stored.record.topology_hash, grid_hash(stored.model)


async def _create(
    client: httpx.AsyncClient, model: object = None, **kwargs: object
) -> httpx.Response:
    response = await client.post(
        "/api/v1/grids",
        json=create_payload(model or sample_grid(), SAMPLE_COORDINATES, **kwargs),  # type: ignore[arg-type]
    )
    assert response.status_code == 201, response.text
    return response


async def test_create_returns_the_grid_with_location_and_etag(
    alpha_api: httpx.AsyncClient, tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    response = await _create(alpha_api, description="A test feeder.")
    body = response.json()

    assert response.headers["etag"] == '"1"'
    assert response.headers["location"] == f"/api/v1/grids/{body['id']}"
    assert uuid.UUID(body["id"]).version == 7  # assigned by the database
    assert body["name"] == "Sample feeder (synthetic)"
    assert body["description"] == "A test feeder."
    assert body["data_origin"] == "synthetic"
    assert body["version"] == 1
    assert body["frequency_hz"] == 50.0
    assert body["element_counts"] == {
        "buses": 5,
        "lines": 2,
        "transformers": 1,
        "loads": 2,
        "generators": 2,
        "external_grids": 1,
        "switches": 3,
    }
    assert body["topology_hash"] == grid_hash(sample_grid())
    stored, rebuilt = await _stored_hash(app_async_engine, tenants["alpha"], body["id"])
    assert stored == rebuilt == body["topology_hash"]


async def test_the_topology_is_returned_exactly_as_stored(
    alpha_api: httpx.AsyncClient,
) -> None:
    grid_id = (await _create(alpha_api)).json()["id"]
    response = await alpha_api.get(f"/api/v1/grids/{grid_id}/topology")

    assert response.status_code == 200
    assert response.headers["etag"] == '"1"'
    body = response.json()
    assert (body["grid_id"], body["version"], body["data_origin"]) == (grid_id, 1, "synthetic")
    expected = topology_payload(sample_grid(), SAMPLE_COORDINATES)
    for group, items in expected.items():
        if isinstance(items, list):
            got = sorted(body["topology"][group], key=lambda item: item["key"])
            assert got == sorted(items, key=lambda item: item["key"]), group
    assert body["topology"]["frequency_hz"] == 50.0


async def test_list_and_read(alpha_api: httpx.AsyncClient) -> None:
    first = (await _create(alpha_api, sample_grid("B feeder (synthetic)"))).json()
    second = (await _create(alpha_api, plain_grid("A feeder (synthetic)"))).json()

    listing = (await alpha_api.get("/api/v1/grids")).json()
    assert [item["name"] for item in listing["items"]] == [
        "A feeder (synthetic)",
        "B feeder (synthetic)",
    ]
    assert (listing["total"], listing["limit"], listing["offset"]) == (2, 50, 0)
    assert listing["items"][0]["element_counts"]["generators"] == 0

    page = (await alpha_api.get("/api/v1/grids?limit=1&offset=1")).json()
    assert [item["id"] for item in page["items"]] == [first["id"]]
    assert page["total"] == 2

    read = await alpha_api.get(f"/api/v1/grids/{second['id']}")
    assert read.status_code == 200
    assert read.headers["etag"] == '"1"'
    assert read.json() == second


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=x"])
async def test_list_parameters_are_bounded(alpha_api: httpx.AsyncClient, query: str) -> None:
    response = await alpha_api.get(f"/api/v1/grids?{query}")
    assert response.status_code == 422


async def test_rename_changes_the_hash_and_describe_does_not(
    alpha_api: httpx.AsyncClient, tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    created = (await _create(alpha_api)).json()
    grid_id = created["id"]

    described = await alpha_api.patch(
        f"/api/v1/grids/{grid_id}", json={"description": "New text"}, headers={"If-Match": '"1"'}
    )
    assert described.status_code == 200
    assert described.headers["etag"] == '"2"'
    assert described.json()["topology_hash"] == created["topology_hash"]
    assert described.json()["description"] == "New text"

    renamed = await alpha_api.patch(
        f"/api/v1/grids/{grid_id}",
        json={"name": "Renamed feeder (synthetic)"},
        headers={"If-Match": '"2"'},
    )
    assert renamed.status_code == 200
    body = renamed.json()
    assert (body["version"], body["name"]) == (3, "Renamed feeder (synthetic)")
    assert body["topology_hash"] != created["topology_hash"]
    assert body["topology_hash"] == grid_hash(sample_grid("Renamed feeder (synthetic)"))
    stored, rebuilt = await _stored_hash(app_async_engine, tenants["alpha"], grid_id)
    assert stored == rebuilt == body["topology_hash"]


async def test_replacing_the_topology(
    alpha_api: httpx.AsyncClient, tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    grid_id = (await _create(alpha_api)).json()["id"]
    new = plain_grid("ignored: a grid keeps its name")
    response = await alpha_api.put(
        f"/api/v1/grids/{grid_id}/topology",
        json=topology_payload(new, {"hv": (9.0, 9.0)}),
        headers={"If-Match": '"1"'},
    )

    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"2"'
    body = response.json()
    assert body["version"] == 2
    assert body["topology"]["generators"] == []
    assert body["topology"]["switches"] == []
    hv = next(bus for bus in body["topology"]["buses"] if bus["key"] == "hv")
    assert hv["diagram"] == {"x": 9.0, "y": 9.0}
    expected_model = plain_grid("Sample feeder (synthetic)")  # the grid's own name
    assert body["topology_hash"] == grid_hash(expected_model)
    stored, rebuilt = await _stored_hash(app_async_engine, tenants["alpha"], grid_id)
    assert stored == rebuilt == body["topology_hash"]

    header = (await alpha_api.get(f"/api/v1/grids/{grid_id}")).json()
    assert header["name"] == "Sample feeder (synthetic)"
    assert header["element_counts"]["generators"] == 0


async def test_changing_the_frequency_is_a_topology_replacement(
    alpha_api: httpx.AsyncClient,
) -> None:
    grid_id = (await _create(alpha_api)).json()["id"]
    payload = topology_payload(sample_grid(), SAMPLE_COORDINATES)
    payload["frequency_hz"] = 60
    response = await alpha_api.put(
        f"/api/v1/grids/{grid_id}/topology", json=payload, headers={"If-Match": '"1"'}
    )
    assert response.status_code == 200
    header = (await alpha_api.get(f"/api/v1/grids/{grid_id}")).json()
    assert header["frequency_hz"] == 60.0


async def test_coordinates_alone_change_the_version_but_not_the_hash(
    alpha_api: httpx.AsyncClient,
) -> None:
    created = (await _create(alpha_api)).json()
    payload = topology_payload(sample_grid(), {"hv": (100.0, -5.0)})
    response = await alpha_api.put(
        f"/api/v1/grids/{created['id']}/topology", json=payload, headers={"If-Match": '"1"'}
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["topology_hash"] == created["topology_hash"]


@pytest.mark.parametrize(
    ("asset_type", "key", "change", "field"),
    [
        ("buses", "c", {"in_service": False}, "in_service"),
        ("lines", "bc", {"in_service": False}, "in_service"),
        ("transformers", "t1", {"name": "Main transformer"}, "name"),
        ("loads", "load-b", {"in_service": False}, "in_service"),
        ("generators", "pv", {"in_service": False, "name": "PV array"}, "in_service"),
        ("external_grids", "upstream", {"name": "Upstream 110 kV"}, "name"),
        ("switches", "s-bc", {"closed": True}, "closed"),
        ("switches", "coupler", {"closed": False, "name": "Coupler D"}, "closed"),
    ],
)
async def test_each_asset_type_changes_name_and_state(
    alpha_api: httpx.AsyncClient,
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    asset_type: str,
    key: str,
    change: dict[str, object],
    field: str,
) -> None:
    created = (await _create(alpha_api)).json()
    grid_id = created["id"]
    url = f"/api/v1/grids/{grid_id}/assets/{asset_type}/{key}"

    response = await alpha_api.patch(url, json=change, headers={"If-Match": '"1"'})

    assert response.status_code == 200, response.text
    assert response.headers["etag"] == '"2"'
    body = response.json()
    assert (body["type"], body["grid_version"], body["grid_id"]) == (asset_type, 2, grid_id)
    for name, value in change.items():
        assert body["asset"][name] == value
    assert body["topology_hash"] != created["topology_hash"]
    stored, rebuilt = await _stored_hash(app_async_engine, tenants["alpha"], grid_id)
    assert stored == rebuilt == body["topology_hash"]

    reread = await alpha_api.get(url)
    assert reread.status_code == 200
    assert reread.json()["asset"] == body["asset"]
    assert reread.headers["etag"] == '"2"'
    assert reread.json()["asset"][field] == change[field]


async def test_listing_one_asset_type(alpha_api: httpx.AsyncClient) -> None:
    grid_id = (await _create(alpha_api)).json()["id"]
    response = await alpha_api.get(f"/api/v1/grids/{grid_id}/assets/switches")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "switches"
    assert sorted(item["key"] for item in body["items"]) == ["cb-t1", "coupler", "s-bc"]
    assert response.headers["etag"] == '"1"'


@pytest.mark.parametrize(
    ("asset_type", "change"),
    [
        ("buses", {"closed": True}),  # closed belongs to switches
        ("switches", {"in_service": False}),  # switches have a position, not a service state
        ("lines", {}),  # nothing to change
        ("lines", {"length_km": 3.0}),  # electrical parameters: replace the topology (D3)
        ("lines", {"in_service": "false"}),  # text is not a boolean
        ("lines", {"in_service": 0}),
        ("lines", {"name": "   "}),
        ("switches", {"closed": None}),
    ],
)
async def test_asset_changes_outside_the_contract_are_rejected(
    alpha_api: httpx.AsyncClient, asset_type: str, change: dict[str, object]
) -> None:
    created = (await _create(alpha_api)).json()
    key = {"buses": "a", "switches": "s-bc", "lines": "ab"}[asset_type]
    response = await alpha_api.patch(
        f"/api/v1/grids/{created['id']}/assets/{asset_type}/{key}",
        json=change,
        headers={"If-Match": '"1"'},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert (await alpha_api.get(f"/api/v1/grids/{created['id']}")).json()["version"] == 1


async def test_unknown_assets_and_asset_types_are_404(alpha_api: httpx.AsyncClient) -> None:
    grid_id = (await _create(alpha_api)).json()["id"]
    missing = await alpha_api.get(f"/api/v1/grids/{grid_id}/assets/lines/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "asset_not_found"

    patch = await alpha_api.patch(
        f"/api/v1/grids/{grid_id}/assets/lines/nope",
        json={"in_service": False},
        headers={"If-Match": '"1"'},
    )
    assert patch.status_code == 404
    assert patch.json()["error"]["code"] == "asset_not_found"
    assert (await alpha_api.get(f"/api/v1/grids/{grid_id}")).json()["version"] == 1

    wrong_type = await alpha_api.get(f"/api/v1/grids/{grid_id}/assets/cables")
    assert wrong_type.status_code == 422  # not one of the seven types


async def test_delete(alpha_api: httpx.AsyncClient) -> None:
    grid_id = (await _create(alpha_api)).json()["id"]
    response = await alpha_api.delete(f"/api/v1/grids/{grid_id}", headers={"If-Match": '"1"'})
    assert response.status_code == 204
    assert response.content == b""
    gone = await alpha_api.get(f"/api/v1/grids/{grid_id}")
    assert gone.status_code == 404
    assert (await alpha_api.get("/api/v1/grids")).json()["total"] == 0


async def test_names_are_unique_per_organisation(
    alpha_api: httpx.AsyncClient, bravo_api: httpx.AsyncClient
) -> None:
    await _create(alpha_api)
    duplicate = await alpha_api.post("/api/v1/grids", json=create_payload(sample_grid()))
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "grid_name_conflict"

    elsewhere = await bravo_api.post("/api/v1/grids", json=create_payload(sample_grid()))
    assert elsewhere.status_code == 201  # another tenant may use the same name

    other = (await _create(alpha_api, plain_grid("Other (synthetic)"))).json()
    rename = await alpha_api.patch(
        f"/api/v1/grids/{other['id']}",
        json={"name": "Sample feeder (synthetic)"},
        headers={"If-Match": '"1"'},
    )
    assert rename.status_code == 409
    assert (await alpha_api.get(f"/api/v1/grids/{other['id']}")).json()["version"] == 1


async def test_the_benchmark_grid_round_trips_through_the_api(
    alpha_api: httpx.AsyncClient, tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    model = cigre_mv.cigre_mv_with_der()
    created = await alpha_api.post(
        "/api/v1/grids", json=create_payload(model, cigre_mv.BUS_DIAGRAM_COORDINATES)
    )
    assert created.status_code == 201
    grid_id = created.json()["id"]
    assert created.json()["topology_hash"] == grid_hash(model)

    topology = (await alpha_api.get(f"/api/v1/grids/{grid_id}/topology")).json()["topology"]
    again = await alpha_api.post(
        "/api/v1/grids",
        json={"name": "Copy (synthetic)", "description": "", "topology": topology},
    )
    assert again.status_code == 201
    stored, rebuilt = await _stored_hash(app_async_engine, tenants["alpha"], again.json()["id"])
    assert stored == rebuilt == grid_hash(replace(model, name="Copy (synthetic)"))
