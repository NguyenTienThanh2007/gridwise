"""The scenario and simulation API over HTTP, as deployed: through the app, as the runtime
role, against a real PostgreSQL database. Jobs are finished by the worker role's functions
(``finish_with_real_result``), never by the API."""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_worker import reproduce
from gridwise_worker.database import WorkerDatabase
from gridwise_worker.supervisor import ChildSupervisor
from tests.integration.conftest import API_ROOT, TestDatabase
from tests.support.api import create_payload, grid_api
from tests.support.grids import sample_grid
from tests.support.simulations import claim, counts, fail, finish_with_real_result, job_row

pytestmark = pytest.mark.integration

PEAK = {"name": "Peak", "modifications": [{"type": "scale_loads", "factor": 1.2}]}
#: Taking the only external grid out of service leaves no slack bus: the engine refuses it.
NO_SUPPLY = {
    "name": "No supply",
    "modifications": [
        {
            "type": "set_in_service",
            "element_type": "external_grid",
            "key": "upstream",
            "in_service": False,
        }
    ],
}


@pytest.fixture(scope="module")
def supervisor() -> Iterator[ChildSupervisor]:
    child = ChildSupervisor()
    child.start()
    yield child
    child.stop()


async def _grid(api: httpx.AsyncClient) -> dict[str, Any]:
    response = await api.post("/api/v1/grids", json=create_payload(sample_grid()))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _scenario(api: httpx.AsyncClient, body: dict[str, Any]) -> str:
    response = await api.post("/api/v1/scenarios", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _submit(
    api: httpx.AsyncClient, grid_id: str, body: dict[str, Any] | None = None, **headers: str
) -> httpx.Response:
    return await api.post(
        f"/api/v1/grids/{grid_id}/simulations",
        json=body or {},
        headers={name.replace("_", "-"): value for name, value in headers.items()},
    )


def _sim_rows(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            **counts(engine),
            "results": connection.execute(text("SELECT count(*) FROM sim.results")).scalar_one(),
        }


# --- scenarios ------------------------------------------------------------------------------


async def test_scenarios_are_created_read_listed_and_deleted(alpha_api: httpx.AsyncClient) -> None:
    created = await alpha_api.post("/api/v1/scenarios", json={**PEAK, "description": "+20 %"})
    assert created.status_code == 201
    body = created.json()
    assert created.headers["location"] == f"/api/v1/scenarios/{body['id']}"
    assert body["specification"] == {
        "schema": "gridwise.scenario/1",
        "modifications": [{"type": "scale_loads", "factor": 1.2}],
    }
    assert set(body) == {"id", "name", "description", "spec_hash", "specification", "created_at"}

    assert (await alpha_api.get(f"/api/v1/scenarios/{body['id']}")).json() == body
    listed = (await alpha_api.get("/api/v1/scenarios")).json()
    assert (listed["total"], [item["id"] for item in listed["items"]]) == (1, [body["id"]])

    duplicate = await alpha_api.post("/api/v1/scenarios", json=PEAK)
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (
        409,
        "scenario_name_conflict",
    )

    assert (await alpha_api.delete(f"/api/v1/scenarios/{body['id']}")).status_code == 204
    gone = await alpha_api.get(f"/api/v1/scenarios/{body['id']}")
    assert (gone.status_code, gone.json()["error"]["code"]) == (404, "scenario_not_found")
    again = await alpha_api.delete(f"/api/v1/scenarios/{body['id']}")
    assert again.status_code == 404


async def test_an_invalid_scenario_reports_the_engines_codes(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    before = _sim_rows(owner_engine)
    response = await alpha_api.post(
        "/api/v1/scenarios",
        json={"name": "x", "modifications": [{"type": "scale_loads", "factor": 1000}]},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "scenario_invalid"
    assert error["details"] == [
        {
            "location": ["body", "modifications", 0],
            "message": "factor must be a finite number with 0 < factor <= 100",
            "type": "invalid_scale_factor",
        }
    ]
    schema_error = await alpha_api.post(
        "/api/v1/scenarios", json={"name": "x", "modifications": [{"type": "trip"}]}
    )
    assert schema_error.json()["error"]["code"] == "validation_error"
    assert _sim_rows(owner_engine) == before


# --- submission -----------------------------------------------------------------------------


async def test_a_submission_is_accepted_and_queued(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    response = await _submit(
        alpha_api, grid["id"], {"configuration": {"max_iterations": 20}}, if_match='"1"'
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert response.headers["location"] == f"/api/v1/simulations/{job['id']}"
    assert "idempotent-replayed" not in response.headers
    assert job["status"] == "queued"
    assert (job["outcome"], job["attempt"], job["max_attempts"]) == (None, 0, 3)
    assert job["source"] == {
        "grid_id": grid["id"],
        "grid_version": grid["version"],
        "topology_hash": grid["topology_hash"],
        "status": "current",
    }
    assert job["scenario"]["id"] is None
    assert job["scenario"]["specification"]["modifications"] == []
    assert job["configuration"]["max_iterations"] == 20
    assert job["configuration"]["algorithm"] == "newton_raphson"
    assert job["engine"]["requested_version"] == "0.3.0"
    assert job["engine"]["executed_version"] is None
    assert job["attempts"] == []
    assert job["failure"] is None

    stored = job_row(owner_engine, uuid.UUID(job["id"]))
    with owner_engine.connect() as connection:
        input_hash = connection.execute(
            text("SELECT content_hash FROM sim.snapshots WHERE id = :id"),
            {"id": stored["input_snapshot_id"]},
        ).scalar_one()
    assert job["input_snapshot_hash"] == input_hash
    assert stored["configuration_hash"] == job["configuration"]["hash"]


async def test_a_submission_with_a_scenario_captures_it(alpha_api: httpx.AsyncClient) -> None:
    grid = await _grid(alpha_api)
    scenario_id = await _scenario(alpha_api, PEAK)
    response = await _submit(alpha_api, grid["id"], {"scenario_id": scenario_id})
    assert response.status_code == 202
    job = response.json()
    assert job["scenario"]["id"] == scenario_id
    assert job["scenario"]["specification"]["modifications"] == PEAK["modifications"]
    # The base topology is the grid's; the scenario changed a copy only.
    assert job["input_snapshot_hash"] != grid["topology_hash"]
    assert (await alpha_api.get(f"/api/v1/grids/{grid['id']}")).json()["version"] == 1


async def test_refused_submissions_store_nothing(
    alpha_api: httpx.AsyncClient, bravo_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    foreign = await _grid(bravo_api)
    breaking = await _scenario(alpha_api, NO_SUPPLY)
    missing_key = await _scenario(
        alpha_api,
        {
            "name": "Missing",
            "modifications": [{"type": "set_switch", "key": "no-such-switch", "closed": True}],
        },
    )
    before = _sim_rows(owner_engine)

    stale = await _submit(alpha_api, grid["id"], if_match='"7"')
    assert (stale.status_code, stale.json()["error"]["code"]) == (412, "version_conflict")
    assert stale.headers["etag"] == '"1"'

    for if_match in ('W/"1"', "*", '"1", "2"', "1", ""):
        malformed = await _submit(alpha_api, grid["id"], if_match=if_match)
        assert (malformed.status_code, malformed.json()["error"]["code"]) == (
            400,
            "invalid_if_match",
        ), if_match

    bad_key = await _submit(alpha_api, grid["id"], idempotency_key="has space")
    assert bad_key.json()["error"]["code"] == "invalid_idempotency_key"

    for grid_id in (foreign["id"], str(uuid.uuid4())):
        not_found = await _submit(alpha_api, grid_id)
        assert (not_found.status_code, not_found.json()["error"]["code"]) == (
            404,
            "grid_not_found",
        )

    no_scenario = await _submit(alpha_api, grid["id"], {"scenario_id": str(uuid.uuid4())})
    assert (no_scenario.status_code, no_scenario.json()["error"]["code"]) == (
        422,
        "scenario_not_found",
    )

    invalid = await _submit(alpha_api, grid["id"], {"scenario_id": breaking})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "simulated_grid_invalid"
    assert [d["type"] for d in invalid.json()["error"]["details"]] == ["missing_external_grid"]

    not_applicable = await _submit(alpha_api, grid["id"], {"scenario_id": missing_key})
    assert not_applicable.json()["error"]["code"] == "scenario_not_applicable"
    assert [d["type"] for d in not_applicable.json()["error"]["details"]] == [
        "scenario_key_not_found"
    ]

    options = await _submit(alpha_api, grid["id"], {"configuration": {"tolerance_mva": 1}})
    assert (options.status_code, options.json()["error"]["code"]) == (422, "validation_error")

    assert _sim_rows(owner_engine) == before


async def test_a_scenario_of_another_tenant_is_not_found(
    alpha_api: httpx.AsyncClient, bravo_api: httpx.AsyncClient
) -> None:
    grid = await _grid(alpha_api)
    foreign = await _scenario(bravo_api, PEAK)
    response = await _submit(alpha_api, grid["id"], {"scenario_id": foreign})
    assert (response.status_code, response.json()["error"]["code"]) == (422, "scenario_not_found")


# --- idempotency ----------------------------------------------------------------------------


async def test_a_repeated_key_replays_the_first_job(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    first = await _submit(alpha_api, grid["id"], idempotency_key="run-1")
    assert first.status_code == 202
    replay = await _submit(alpha_api, grid["id"], idempotency_key="run-1")
    assert replay.status_code == 200
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.headers["location"] == first.headers["location"]
    assert replay.json()["id"] == first.json()["id"]

    different = await _submit(
        alpha_api, grid["id"], {"configuration": {"max_iterations": 5}}, idempotency_key="run-1"
    )
    assert (different.status_code, different.json()["error"]["code"]) == (
        422,
        "idempotency_key_reused",
    )
    assert counts(owner_engine)["jobs"] == 1


async def test_concurrent_submissions_with_one_key_make_one_job(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    responses = await asyncio.gather(
        *(_submit(alpha_api, grid["id"], idempotency_key="together") for _ in range(4))
    )
    assert sorted(response.status_code for response in responses) == [200, 200, 200, 202]
    assert len({response.json()["id"] for response in responses}) == 1
    assert counts(owner_engine)["jobs"] == 1


# --- listing and detail ---------------------------------------------------------------------


async def test_jobs_are_listed_newest_first_and_filtered(alpha_api: httpx.AsyncClient) -> None:
    one = await _grid(alpha_api)
    two = await _grid_named(alpha_api)
    first = (await _submit(alpha_api, one["id"])).json()
    second = (await _submit(alpha_api, two["id"])).json()
    third = (await _submit(alpha_api, one["id"])).json()
    await alpha_api.post(f"/api/v1/simulations/{first['id']}/cancel")

    listed = (await alpha_api.get("/api/v1/simulations")).json()
    assert [item["id"] for item in listed["items"]] == [third["id"], second["id"], first["id"]]
    assert (listed["total"], listed["limit"], listed["offset"]) == (3, 50, 0)
    assert all("attempts" not in item for item in listed["items"])

    page = (await alpha_api.get("/api/v1/simulations", params={"limit": 1, "offset": 1})).json()
    assert ([item["id"] for item in page["items"]], page["total"]) == ([second["id"]], 3)

    by_grid = (await alpha_api.get("/api/v1/simulations", params={"grid_id": one["id"]})).json()
    assert [item["id"] for item in by_grid["items"]] == [third["id"], first["id"]]
    cancelled = (await alpha_api.get("/api/v1/simulations", params={"status": "cancelled"})).json()
    assert [item["id"] for item in cancelled["items"]] == [first["id"]]

    created = datetime.fromisoformat(second["created_at"])
    after = (
        await alpha_api.get("/api/v1/simulations", params={"submitted_after": created.isoformat()})
    ).json()
    assert [item["id"] for item in after["items"]] == [third["id"], second["id"]]
    before = (
        await alpha_api.get("/api/v1/simulations", params={"submitted_before": created.isoformat()})
    ).json()
    assert [item["id"] for item in before["items"]] == [first["id"]]
    future = datetime.now(UTC) + timedelta(days=1)
    empty = (
        await alpha_api.get("/api/v1/simulations", params={"submitted_after": future.isoformat()})
    ).json()
    assert (empty["items"], empty["total"]) == ([], 0)

    for params in (
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"status": "done"},
        {"grid_id": "nope"},
        {"submitted_after": "2026-11-14T12:00:00"},  # no time zone
    ):
        response = await alpha_api.get("/api/v1/simulations", params=params)
        assert (response.status_code, response.json()["error"]["code"]) == (
            422,
            "validation_error",
        ), params


async def test_the_source_status_follows_the_grid(alpha_api: httpx.AsyncClient) -> None:
    grid = await _grid(alpha_api)
    job = (await _submit(alpha_api, grid["id"])).json()
    path = f"/api/v1/simulations/{job['id']}"
    assert (await alpha_api.get(path)).json()["source"]["status"] == "current"

    renamed = await alpha_api.patch(
        f"/api/v1/grids/{grid['id']}", json={"name": "Renamed"}, headers={"If-Match": '"1"'}
    )
    assert renamed.status_code == 200
    changed = (await alpha_api.get(path)).json()
    assert changed["source"]["status"] == "changed"
    assert changed["source"]["grid_version"] == 1
    listed = (await alpha_api.get("/api/v1/simulations")).json()["items"][0]
    assert listed["source"]["status"] == "changed"

    deleted = await alpha_api.delete(f"/api/v1/grids/{grid['id']}", headers={"If-Match": '"2"'})
    assert deleted.status_code == 204
    gone = (await alpha_api.get(path)).json()
    assert gone["source"]["status"] == "deleted"
    assert gone["source"]["grid_id"] is None
    assert gone["input_snapshot_hash"] == job["input_snapshot_hash"]


async def test_attempts_are_listed_without_worker_ids(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    job = (await _submit(alpha_api, grid["id"])).json()
    job_id = uuid.UUID(job["id"])
    with owner_engine.begin() as connection:
        claim(connection, job_id, worker="host-7:991")
        fail(connection, job_id, code="execution_timeout")
    detail = await alpha_api.get(f"/api/v1/simulations/{job_id}")
    body = detail.json()
    assert body["status"] == "failed"
    assert body["failure"] == {
        "code": "execution_timeout",
        "message": "The computation did not finish within the time limit.",
    }
    assert "host-7" not in detail.text
    assert all(
        set(item) == {"attempt", "started_at", "ended_at", "ended_by"} for item in body["attempts"]
    )


# --- cancellation ---------------------------------------------------------------------------


async def test_only_a_queued_job_can_be_cancelled(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    queued = (await _submit(alpha_api, grid["id"])).json()
    cancelled = await alpha_api.post(f"/api/v1/simulations/{queued['id']}/cancel")
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None

    again = await alpha_api.post(f"/api/v1/simulations/{queued['id']}/cancel")
    assert again.status_code == 409
    error = again.json()["error"]
    assert error["code"] == "job_not_cancellable"
    assert error["details"][0]["type"] == "cancelled"

    running = (await _submit(alpha_api, grid["id"])).json()
    with owner_engine.begin() as connection:
        claim(connection, uuid.UUID(running["id"]))
    refused = await alpha_api.post(f"/api/v1/simulations/{running['id']}/cancel")
    assert refused.status_code == 409
    assert refused.json()["error"]["details"][0]["type"] == "running"
    assert job_row(owner_engine, uuid.UUID(running["id"]))["status"] == "running"

    missing = await alpha_api.post(f"/api/v1/simulations/{uuid.uuid4()}/cancel")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "job_not_found")


async def test_a_cancel_racing_a_claim_has_one_winner(
    alpha_api: httpx.AsyncClient, worker_engine: Engine, owner_engine: Engine
) -> None:
    for _ in range(5):
        grid = await _grid_named(alpha_api)
        job = (await _submit(alpha_api, grid["id"])).json()
        database = WorkerDatabase(worker_engine, worker_id="racer", lease_seconds=60)
        cancel, lease = await asyncio.gather(
            alpha_api.post(f"/api/v1/simulations/{job['id']}/cancel"),
            asyncio.to_thread(database.claim),
        )
        status = job_row(owner_engine, uuid.UUID(job["id"]))["status"]
        if cancel.status_code == 200:
            assert (lease, status) == (None, "cancelled")
        else:
            assert cancel.status_code == 409
            assert lease is not None
            assert lease.job_id == uuid.UUID(job["id"])
            assert status == "running"
            with owner_engine.begin() as connection:
                fail(connection, lease.job_id)


_names = iter(range(1_000_000))


async def _grid_named(api: httpx.AsyncClient) -> dict[str, Any]:
    response = await api.post(
        "/api/v1/grids", json={**create_payload(sample_grid()), "name": f"Grid {next(_names)}"}
    )
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


# --- results --------------------------------------------------------------------------------


async def test_a_converged_result_has_its_summary_and_document(
    alpha_api: httpx.AsyncClient, worker_engine: Engine, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    job = (await _submit(alpha_api, grid["id"])).json()
    not_yet = await alpha_api.get(f"/api/v1/simulations/{job['id']}/result")
    assert (not_yet.status_code, not_yet.json()["error"]["code"]) == (409, "result_not_available")
    assert not_yet.json()["error"]["details"][0]["type"] == "queued"

    assert finish_with_real_result(worker_engine) == uuid.UUID(job["id"])
    detail = (await alpha_api.get(f"/api/v1/simulations/{job['id']}")).json()
    assert (detail["status"], detail["outcome"]) == ("completed", "converged")
    assert detail["engine"]["solver_name"] == "pandapower"

    response = await alpha_api.get(f"/api/v1/simulations/{job['id']}/result")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "converged"
    with owner_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT result_hash FROM sim.results WHERE job_id = :id"), {"id": job["id"]}
        ).scalar_one()
    assert body["result_hash"] == stored
    summary = body["summary"]
    assert (summary["schema"], summary["converged"]) == ("gridwise.result-summary/1", True)
    assert summary["totals"]["served_load_mw"] == pytest.approx(2.0)
    assert summary["unsupplied_bus_ids"] == ["c"]
    assert body["result"]["schema"] == "gridwise.power-flow-result-document/1"
    # De-energised elements have no values, never zero.
    bus_c = next(bus for bus in body["result"]["buses"] if bus["bus_id"] == "c")
    assert bus_c["voltage_pu"] is None


async def test_a_run_that_did_not_converge_returns_no_values(
    alpha_api: httpx.AsyncClient, worker_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    scenario_id = await _scenario(
        alpha_api, {"name": "100x", "modifications": [{"type": "scale_loads", "factor": 100}]}
    )
    job = (await _submit(alpha_api, grid["id"], {"scenario_id": scenario_id})).json()
    finish_with_real_result(worker_engine)
    body = (await alpha_api.get(f"/api/v1/simulations/{job['id']}/result")).json()
    assert (body["outcome"], body["result_hash"], body["result"]) == ("not_converged", None, None)
    summary = body["summary"]
    assert summary["converged"] is False
    assert all(
        value is None for key, value in summary.items() if key not in {"schema", "converged"}
    )


async def test_failed_and_cancelled_jobs_have_no_result(
    alpha_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    failed = (await _submit(alpha_api, grid["id"])).json()
    with owner_engine.begin() as connection:
        claim(connection, uuid.UUID(failed["id"]))
        fail(connection, uuid.UUID(failed["id"]))
    cancelled = (await _submit(alpha_api, grid["id"])).json()
    await alpha_api.post(f"/api/v1/simulations/{cancelled['id']}/cancel")
    for job, status in ((failed, "failed"), (cancelled, "cancelled")):
        response = await alpha_api.get(f"/api/v1/simulations/{job['id']}/result")
        assert response.status_code == 409
        assert response.json()["error"]["details"][0]["type"] == status
    missing = await alpha_api.get(f"/api/v1/simulations/{uuid.uuid4()}/result")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "job_not_found")


async def test_a_damaged_result_is_an_internal_error_with_no_values(
    alpha_api: httpx.AsyncClient, worker_engine: Engine, admin_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    job = (await _submit(alpha_api, grid["id"])).json()
    finish_with_real_result(worker_engine)
    with admin_engine.begin() as connection:
        # The superuser bypasses the immutability trigger, as a damaged disk would.
        connection.execute(text("ALTER TABLE sim.results DISABLE TRIGGER USER"))
        # Its hash is updated with it, so only reading the document finds the damage.
        connection.execute(
            text(
                "UPDATE sim.results SET document = :document, "
                "document_hash = encode(sha256(convert_to(:document, 'UTF8')), 'hex') "
                "WHERE job_id = :id"
            ),
            {"id": job["id"], "document": '{"schema": "not-a-result"}'},
        )
        connection.execute(text("ALTER TABLE sim.results ENABLE TRIGGER USER"))
    response = await alpha_api.get(f"/api/v1/simulations/{job['id']}/result")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "summary" not in response.text
    assert "buses" not in response.text


# --- reproductions --------------------------------------------------------------------------


async def test_the_reproduction_history_is_read_only_and_newest_first(
    alpha_api: httpx.AsyncClient,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    grid = await _grid(alpha_api)
    job = (await _submit(alpha_api, grid["id"])).json()
    path = f"/api/v1/simulations/{job['id']}/reproductions"
    empty = (await alpha_api.get(path)).json()
    assert (empty["items"], empty["total"]) == ([], 0)

    finish_with_real_result(worker_engine)
    database = WorkerDatabase(worker_engine, worker_id="reproducer-host:1", lease_seconds=60)
    for _ in range(2):
        verdict = await asyncio.to_thread(
            reproduce.reproduce_job,
            database,
            supervisor,
            tenants["alpha"],
            uuid.UUID(job["id"]),
            timeout_seconds=60,
        )
        assert verdict == "match"
    before = _sim_rows(owner_engine)
    response = await alpha_api.get(path)
    body = response.json()
    assert body["total"] == 2
    assert [item["verdict"] for item in body["items"]] == ["match", "match"]
    assert body["items"][0]["created_at"] >= body["items"][1]["created_at"]
    assert body["items"][0]["solver_name"] == "pandapower"
    assert "reproducer-host" not in response.text
    assert "worker_id" not in body["items"][0]
    assert _sim_rows(owner_engine) == before  # reading reproduces nothing

    page = (await alpha_api.get(path, params={"limit": 1})).json()
    assert (len(page["items"]), page["total"]) == (1, 2)


# --- tenants and environments ---------------------------------------------------------------


async def test_another_tenants_simulations_are_indistinguishable_from_missing_ones(
    alpha_api: httpx.AsyncClient, bravo_api: httpx.AsyncClient, owner_engine: Engine
) -> None:
    grid = await _grid(alpha_api)
    job = (await _submit(alpha_api, grid["id"])).json()
    scenario = await _scenario(alpha_api, PEAK)
    before = _sim_rows(owner_engine)
    for job_id in (job["id"], str(uuid.uuid4())):
        for method, path in (
            ("GET", f"/api/v1/simulations/{job_id}"),
            ("POST", f"/api/v1/simulations/{job_id}/cancel"),
            ("GET", f"/api/v1/simulations/{job_id}/result"),
            ("GET", f"/api/v1/simulations/{job_id}/reproductions"),
        ):
            response = await bravo_api.request(method, path)
            assert response.status_code == 404, (method, path)
            error = response.json()["error"]
            assert (error["code"], error["message"]) == (
                "job_not_found",
                "Simulation job not found",
            )
    for scenario_id in (scenario, str(uuid.uuid4())):
        for method in ("GET", "DELETE"):
            response = await bravo_api.request(method, f"/api/v1/scenarios/{scenario_id}")
            assert (response.status_code, response.json()["error"]["code"]) == (
                404,
                "scenario_not_found",
            )
    assert (await bravo_api.get("/api/v1/simulations")).json()["total"] == 0
    assert (await bravo_api.get("/api/v1/scenarios")).json()["total"] == 0
    assert (await bravo_api.get("/api/v1/simulations", params={"grid_id": grid["id"]})).json()[
        "items"
    ] == []
    assert _sim_rows(owner_engine) == before
    assert job_row(owner_engine, uuid.UUID(job["id"]))["status"] == "queued"


async def test_without_a_development_tenant_nothing_is_queried(
    database: TestDatabase, migrated: None
) -> None:
    async with grid_api(database.app_url, None) as api:
        some_id = uuid.uuid4()
        for method, path in (
            ("GET", "/api/v1/scenarios"),
            ("POST", f"/api/v1/grids/{some_id}/simulations"),
            ("GET", "/api/v1/simulations"),
            ("GET", f"/api/v1/simulations/{some_id}"),
            ("GET", f"/api/v1/simulations/{some_id}/result"),
        ):
            response = await api.request(method, path, json={} if method == "POST" else None)
            assert response.status_code == 503, (method, path)
            assert response.json()["error"]["code"] == "development_tenant_not_configured"


# --- the boundary ---------------------------------------------------------------------------


def test_the_api_never_loads_the_solver(
    tenants: dict[str, uuid.UUID], database: TestDatabase, app_async_engine: AsyncEngine
) -> None:
    """In a fresh interpreter: create, submit, read, list and cancel over HTTP, and check
    that no numerical library was ever imported."""
    code = f"""
import asyncio, sys, uuid
from tests.support.api import create_payload, grid_api
from tests.support.grids import sample_grid

async def main():
    async with grid_api({database.app_url!r}, uuid.UUID({str(tenants["alpha"])!r})) as api:
        grid = (await api.post("/api/v1/grids", json=create_payload(sample_grid()))).json()
        job = (await api.post(f"/api/v1/grids/{{grid['id']}}/simulations", json={{}})).json()
        await api.get(f"/api/v1/simulations/{{job['id']}}")
        await api.get("/api/v1/simulations")
        await api.get(f"/api/v1/simulations/{{job['id']}}/result")
        await api.get(f"/api/v1/simulations/{{job['id']}}/reproductions")
        await api.post(f"/api/v1/simulations/{{job['id']}}/cancel")
    loaded = sorted(m for m in ("pandapower", "pandas", "numpy", "scipy") if m in sys.modules)
    print(job["status"], loaded)

asyncio.run(main())
"""
    source = API_ROOT.parents[1]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(API_ROOT / "src"), str(API_ROOT), str(source / "packages/grid-engine/src")]
        ),
    }
    completed = subprocess.run(  # noqa: S603  (fixed interpreter, code defined here)
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
        cwd=API_ROOT,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert completed.stdout.strip().splitlines()[-1] == "queued []"
