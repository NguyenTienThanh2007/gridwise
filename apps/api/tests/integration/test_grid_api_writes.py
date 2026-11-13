"""What a write must satisfy over HTTP: preconditions, validity, atomicity, concurrency.

The common check: after a refused write, the database is unchanged, row for row, including
ids, versions and timestamps.
"""

import asyncio
import json
import math
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine

from gridwise_api.repositories import grids as grid_repository
from tests.integration.conftest import TestDatabase
from tests.support.api import create_payload, database_snapshot, grid_api, topology_payload
from tests.support.grids import SAMPLE_COORDINATES, sample_grid

pytestmark = pytest.mark.integration


@pytest.fixture
async def grid_id(alpha_api: httpx.AsyncClient) -> str:
    response = await alpha_api.post(
        "/api/v1/grids", json=create_payload(sample_grid(), SAMPLE_COORDINATES)
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _writes(grid_id: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    """One of each kind of write, all valid apart from their preconditions."""
    return [
        ("PATCH", f"/api/v1/grids/{grid_id}", {"description": "changed"}),
        ("PUT", f"/api/v1/grids/{grid_id}/topology", topology_payload(sample_grid())),
        ("PATCH", f"/api/v1/grids/{grid_id}/assets/switches/s-bc", {"closed": True}),
        ("DELETE", f"/api/v1/grids/{grid_id}", None),
    ]


async def _send(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    body: dict[str, Any] | None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return await client.request(method, url, json=body, headers=headers or {})


# --- If-Match ---------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(4), ids=["header", "topology", "asset", "delete"])
async def test_a_write_without_if_match_is_428_and_changes_nothing(
    alpha_api: httpx.AsyncClient, grid_id: str, owner_engine: Engine, index: int
) -> None:
    before = database_snapshot(owner_engine)
    method, url, body = _writes(grid_id)[index]
    response = await _send(alpha_api, method, url, body)
    assert response.status_code == 428
    assert response.json()["error"]["code"] == "precondition_required"
    assert database_snapshot(owner_engine) == before


@pytest.mark.parametrize("index", range(4), ids=["header", "topology", "asset", "delete"])
@pytest.mark.parametrize("stale", ['"2"', '"0"', '"99"'])
async def test_a_stale_if_match_is_412_with_the_current_etag(
    alpha_api: httpx.AsyncClient, grid_id: str, owner_engine: Engine, index: int, stale: str
) -> None:
    before = database_snapshot(owner_engine)
    method, url, body = _writes(grid_id)[index]
    response = await _send(alpha_api, method, url, body, {"If-Match": stale})
    if stale == '"0"':
        assert response.status_code == 400  # not a version: versions start at 1
        assert response.json()["error"]["code"] == "invalid_if_match"
    else:
        assert response.status_code == 412
        assert response.json()["error"]["code"] == "version_conflict"
        assert response.headers["etag"] == '"1"'
    assert database_snapshot(owner_engine) == before


@pytest.mark.parametrize(
    "value", ["*", 'W/"1"', '"1", "2"', "1", '"one"', '""', '"1', '"-1"', '"99999999999"']
)
async def test_a_malformed_if_match_is_400(
    alpha_api: httpx.AsyncClient, grid_id: str, owner_engine: Engine, value: str
) -> None:
    before = database_snapshot(owner_engine)
    response = await alpha_api.patch(
        f"/api/v1/grids/{grid_id}", json={"description": "x"}, headers={"If-Match": value}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_if_match"
    assert database_snapshot(owner_engine) == before


async def test_the_etag_of_a_response_is_the_if_match_of_the_next_write(
    alpha_api: httpx.AsyncClient, grid_id: str
) -> None:
    etag = (await alpha_api.get(f"/api/v1/grids/{grid_id}/topology")).headers["etag"]
    for step in range(3):
        response = await alpha_api.patch(
            f"/api/v1/grids/{grid_id}/assets/loads/load-b",
            json={"name": f"Load B, take {step}"},
            headers={"If-Match": etag},
        )
        assert response.status_code == 200
        etag = response.headers["etag"]
    assert etag == '"4"'


# --- invalid grids are never stored ------------------------------------------------------


def _invalid_topologies() -> list[tuple[str, Callable[[dict[str, Any]], None], str]]:
    def set_(group: str, key: str, **values: object) -> Callable[[dict[str, Any]], None]:
        def change(topology: dict[str, Any]) -> None:
            for item in topology[group]:
                if item["key"] == key:
                    item.update(values)

        return change

    def add(group: str, item: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
        return lambda topology: topology[group].append(item)

    def frequency(topology: dict[str, Any]) -> None:
        topology["frequency_hz"] = 55

    def no_buses(topology: dict[str, Any]) -> None:
        for group in topology:
            if isinstance(topology[group], list):
                topology[group] = []

    return [
        ("unknown bus", set_("lines", "ab", to_bus_key="nowhere"), "unknown_bus_reference"),
        ("line across levels", set_("lines", "ab", from_bus_key="hv"), "line_voltage_mismatch"),
        ("negative resistance", set_("lines", "ab", r_ohm_per_km=-0.1), "negative_line_resistance"),
        (
            "transformer upside down",
            set_("transformers", "t1", hv_bus_key="a", lv_bus_key="hv"),
            "transformer_voltage_mismatch",
        ),
        (
            "second voltage controller",
            set_("generators", "chp", bus_key="hv"),
            "multiple_voltage_controllers_on_bus",
        ),
        (
            "switch off its line",
            set_("switches", "s-bc", bus_key="a"),
            "switch_not_at_element_terminal",
        ),
        (
            "no source",
            set_("external_grids", "upstream", in_service=False),
            "missing_external_grid",
        ),
        ("frequency", frequency, "invalid_frequency"),
        ("empty network", no_buses, "no_buses"),
        (
            "duplicate key",
            add(
                "loads",
                {"key": "load-b", "name": "Twin", "bus_key": "b", "p_mw": 1.0, "q_mvar": 0.0},
            ),
            "duplicate_element_id",
        ),
        (
            "generator mode fields",
            set_("generators", "pv", voltage_setpoint_pu=1.0),
            "invalid_generator_parameters",
        ),
    ]


INVALID = _invalid_topologies()


@pytest.mark.parametrize(("label", "corrupt", "code"), INVALID, ids=[case[0] for case in INVALID])
async def test_an_invalid_grid_is_not_created(
    alpha_api: httpx.AsyncClient,
    owner_engine: Engine,
    migrated: None,
    label: str,
    corrupt: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    before = database_snapshot(owner_engine)
    payload = create_payload(sample_grid())
    corrupt(payload["topology"])
    response = await alpha_api.post("/api/v1/grids", json=payload)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "grid_validation_failed"
    assert code in {detail["type"] for detail in error["details"]}
    assert database_snapshot(owner_engine) == before


@pytest.mark.parametrize(("label", "corrupt", "code"), INVALID, ids=[case[0] for case in INVALID])
async def test_an_invalid_topology_does_not_replace_a_valid_one(
    alpha_api: httpx.AsyncClient,
    grid_id: str,
    owner_engine: Engine,
    label: str,
    corrupt: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    before = database_snapshot(owner_engine)
    payload = topology_payload(sample_grid(), SAMPLE_COORDINATES)
    corrupt(payload)
    response = await alpha_api.put(
        f"/api/v1/grids/{grid_id}/topology", json=payload, headers={"If-Match": '"1"'}
    )
    assert response.status_code == 422
    assert code in {detail["type"] for detail in response.json()["error"]["details"]}
    assert database_snapshot(owner_engine) == before


async def test_an_asset_change_that_breaks_the_grid_is_refused(
    alpha_api: httpx.AsyncClient, grid_id: str, owner_engine: Engine
) -> None:
    """Taking the only source out of service would leave the network without a slack."""
    before = database_snapshot(owner_engine)
    response = await alpha_api.patch(
        f"/api/v1/grids/{grid_id}/assets/external_grids/upstream",
        json={"in_service": False},
        headers={"If-Match": '"1"'},
    )
    assert response.status_code == 422
    details = response.json()["error"]["details"]
    assert [detail["type"] for detail in details] == ["missing_external_grid"]
    assert database_snapshot(owner_engine) == before


async def test_validation_details_name_the_element_and_field(
    alpha_api: httpx.AsyncClient, migrated: None
) -> None:
    payload = create_payload(sample_grid())
    for line in payload["topology"]["lines"]:
        if line["key"] == "ab":
            line["length_km"] = 0.0
    response = await alpha_api.post("/api/v1/grids", json=payload)
    (detail,) = response.json()["error"]["details"]
    assert detail == {
        "location": ["line", "ab", "length_km"],
        "message": "length_km must be greater than 0",
        "type": "invalid_line_length",
    }


# --- strict request schemas --------------------------------------------------------------


def _strict_cases() -> list[tuple[str, Callable[[dict[str, Any]], None]]]:
    def bus(**values: object) -> Callable[[dict[str, Any]], None]:
        return lambda payload: payload["topology"]["buses"][0].update(values)

    return [
        ("unknown field", lambda payload: payload.update(owner="someone")),
        ("data_origin", lambda payload: payload.update(data_origin="measured")),
        ("client id", lambda payload: payload.update(id=str(uuid.uuid4()))),
        ("version", lambda payload: payload.update(version=7)),
        ("text boolean", bus(in_service="false")),
        ("number boolean", bus(in_service=1)),
        ("text number", bus(nominal_voltage_kv="110")),
        ("boolean number", bus(nominal_voltage_kv=True)),
        ("NaN", bus(nominal_voltage_kv=math.nan)),
        ("infinity", bus(nominal_voltage_kv=math.inf)),
        ("blank name", lambda payload: payload.update(name="   ")),
        ("empty name", lambda payload: payload.update(name="")),
        ("blank element name", bus(name=" ")),
        ("key with space", bus(key="bus one")),
        ("key too long", bus(key="k" * 201)),
        ("unknown element field", bus(row_id=str(uuid.uuid4()))),
        ("unknown switch kind", lambda p: p["topology"]["switches"][0].update(kind="fuse")),
        (
            "tap position as decimal",
            lambda p: p["topology"]["transformers"][0]["tap"].update(position=1.0),
        ),
        ("description too long", lambda payload: payload.update(description="x" * 2001)),
    ]


STRICT = _strict_cases()


@pytest.mark.parametrize(("label", "corrupt"), STRICT, ids=[case[0] for case in STRICT])
async def test_malformed_requests_are_rejected_before_validation(
    alpha_api: httpx.AsyncClient,
    owner_engine: Engine,
    migrated: None,
    label: str,
    corrupt: Callable[[dict[str, Any]], None],
) -> None:
    before = database_snapshot(owner_engine)
    payload = create_payload(sample_grid(), SAMPLE_COORDINATES)
    corrupt(payload)
    # Serialised by hand: httpx refuses NaN and infinity, which a client can still send.
    response = await alpha_api.post(
        "/api/v1/grids",
        content=json.dumps(payload, allow_nan=True),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    assert database_snapshot(owner_engine) == before


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
        None,
    ],
)
async def test_a_body_a_cross_site_form_could_send_is_refused(
    alpha_api: httpx.AsyncClient,
    owner_engine: Engine,
    migrated: None,
    content_type: str | None,
) -> None:
    """Without authentication, this is what keeps a form on another site from writing.

    An HTML form can send these content types without a CORS preflight. Only
    ``application/json`` is accepted, and a browser sends it cross-site only after a
    preflight, which CORS refuses for origins that are not configured.
    """
    before = database_snapshot(owner_engine)
    headers = {"Origin": "http://evil.example.test"}
    if content_type is not None:
        headers["Content-Type"] = content_type
    response = await alpha_api.post(
        "/api/v1/grids", content=json.dumps(create_payload(sample_grid())), headers=headers
    )
    assert response.status_code == 422
    assert "access-control-allow-origin" not in response.headers
    assert database_snapshot(owner_engine) == before


async def test_rejected_input_is_never_echoed(alpha_api: httpx.AsyncClient, migrated: None) -> None:
    payload = create_payload(sample_grid())
    payload["topology"]["buses"][0]["name"] = 12345678  # wrong type, distinctive value
    response = await alpha_api.post("/api/v1/grids", json=payload)
    assert response.status_code == 422
    assert "12345678" not in response.text


async def test_an_integer_is_accepted_where_a_decimal_is_expected(
    alpha_api: httpx.AsyncClient, migrated: None
) -> None:
    payload = create_payload(sample_grid())
    payload["topology"]["buses"][0]["nominal_voltage_kv"] = 110
    response = await alpha_api.post("/api/v1/grids", json=payload)
    assert response.status_code == 201
    assert response.json()["topology_hash"] == create_hash()


def create_hash() -> str:
    from gridwise_grid_engine import grid_hash

    return grid_hash(sample_grid())  # 110 and 110.0 are the same number


# --- atomicity ----------------------------------------------------------------------------


async def test_a_failure_after_the_old_elements_are_deleted_rolls_everything_back(
    alpha_api: httpx.AsyncClient,
    grid_id: str,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new elements are written, the old ones deleted, then the header write fails."""
    before = database_snapshot(owner_engine)

    async def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(grid_repository, "save_grid_header", fail)
    response = await alpha_api.put(
        f"/api/v1/grids/{grid_id}/topology",
        json=topology_payload(sample_grid()),
        headers={"If-Match": '"1"'},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "injected" not in response.text
    assert database_snapshot(owner_engine) == before


async def test_a_failure_while_creating_leaves_nothing_behind(
    alpha_api: httpx.AsyncClient,
    owner_engine: Engine,
    migrated: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = database_snapshot(owner_engine)
    original = grid_repository.create_grid

    async def fail_after_insert(*args: Any, **kwargs: Any) -> Any:
        await original(*args, **kwargs)
        raise RuntimeError("injected failure")

    monkeypatch.setattr(grid_repository, "create_grid", fail_after_insert)
    response = await alpha_api.post("/api/v1/grids", json=create_payload(sample_grid()))
    assert response.status_code == 500
    assert database_snapshot(owner_engine) == before


# --- concurrency --------------------------------------------------------------------------


async def test_of_two_concurrent_writes_with_the_same_if_match_exactly_one_succeeds(
    alpha_api: httpx.AsyncClient, grid_id: str
) -> None:
    url = f"/api/v1/grids/{grid_id}/assets/lines/ab"
    first, second = await asyncio.gather(
        alpha_api.patch(url, json={"name": "first"}, headers={"If-Match": '"1"'}),
        alpha_api.patch(url, json={"name": "second"}, headers={"If-Match": '"1"'}),
    )
    assert sorted((first.status_code, second.status_code)) == [200, 412]
    winner = first if first.status_code == 200 else second
    stored = (await alpha_api.get(url)).json()
    assert stored["grid_version"] == 2
    assert stored["asset"]["name"] == winner.json()["asset"]["name"]


async def test_concurrent_writes_of_different_kinds_are_serialised(
    alpha_api: httpx.AsyncClient, grid_id: str
) -> None:
    responses = await asyncio.gather(
        *(
            _send(alpha_api, method, url, body, {"If-Match": '"1"'})
            for method, url, body in _writes(grid_id)[:3]
        )
    )
    assert sorted(response.status_code for response in responses) == [200, 412, 412]


async def test_of_two_concurrent_creates_with_one_name_one_conflicts(
    alpha_api: httpx.AsyncClient, migrated: None
) -> None:
    payload = create_payload(sample_grid())
    first, second = await asyncio.gather(
        alpha_api.post("/api/v1/grids", json=payload),
        alpha_api.post("/api/v1/grids", json=payload),
    )
    assert sorted((first.status_code, second.status_code)) == [201, 409]
    assert (await alpha_api.get("/api/v1/grids")).json()["total"] == 1


# --- limits -------------------------------------------------------------------------------


async def test_a_body_over_the_limit_is_413(
    tenants: dict[str, uuid.UUID], database: TestDatabase, owner_engine: Engine
) -> None:
    before = database_snapshot(owner_engine)
    async with grid_api(database.app_url, tenants["alpha"], max_request_body_bytes=2048) as client:
        payload = create_payload(sample_grid(), description="x" * 1500)
        declared = await client.post("/api/v1/grids", json=payload)
        assert declared.status_code == 413
        assert declared.json()["error"]["code"] == "request_too_large"

        async def chunks() -> Any:
            for _ in range(10):
                yield b" " * 1000

        streamed = await client.post(
            "/api/v1/grids", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert streamed.status_code == 413
    assert database_snapshot(owner_engine) == before


async def test_a_streamed_body_within_the_limit_is_accepted(
    tenants: dict[str, uuid.UUID], database: TestDatabase, migrated: None
) -> None:
    body = json.dumps(create_payload(sample_grid())).encode()

    async def chunks() -> Any:
        for start in range(0, len(body), 500):
            yield body[start : start + 500]

    async with grid_api(database.app_url, tenants["alpha"]) as client:
        response = await client.post(
            "/api/v1/grids", content=chunks(), headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 201


async def test_a_grid_with_too_many_elements_is_refused(
    tenants: dict[str, uuid.UUID], database: TestDatabase, owner_engine: Engine
) -> None:
    before = database_snapshot(owner_engine)
    async with grid_api(database.app_url, tenants["alpha"], grid_max_elements=10) as client:
        response = await client.post("/api/v1/grids", json=create_payload(sample_grid()))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "grid_too_large"
    assert database_snapshot(owner_engine) == before
