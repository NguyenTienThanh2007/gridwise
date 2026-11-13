"""Submitting a simulation: what is captured, what is refused, and that nothing is stored
unless everything succeeds. All as the runtime role, through the service."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import simulations as sim_repository
from gridwise_api.services import simulations as sim
from gridwise_api.services.grids import AssetChange, GridService
from gridwise_api.simulation.configuration import SimulationConfiguration
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine import grid_hash
from gridwise_grid_engine.scenarios import (
    ScenarioErrorCode,
    apply_scenario,
    demand_increase,
    scenario_document,
    scenario_hash,
)
from gridwise_grid_engine.snapshots import grid_from_snapshot, snapshot_hash
from tests.integration.conftest import TestDatabase
from tests.support.grids import sample_grid
from tests.support.simulations import counts, job_row, service, stored_grid

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def alpha(tenants: dict[str, uuid.UUID]) -> uuid.UUID:
    return tenants["alpha"]


@pytest.fixture
async def grid_id(alpha: uuid.UUID, app_async_engine: AsyncEngine) -> uuid.UUID:
    return await stored_grid(app_async_engine, alpha)


async def _scenario(
    engine: AsyncEngine, organization: uuid.UUID, document: object, name: str = "Scenario"
) -> uuid.UUID:
    record = await service(engine).create_scenario(
        organization, name=name, description="", document=document
    )
    return record.id


async def test_a_submission_captures_the_grid_exactly(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    submission = await service(app_async_engine).submit(alpha, grid_id)
    job = submission.job

    assert submission.created is True
    assert (job.status, job.attempt, job.outcome, job.failure_code) == ("queued", 0, None, None)
    assert (job.source_grid_id, job.source_grid_version) == (grid_id, 1)
    assert job.source_topology_hash == grid_hash(sample_grid())
    assert job.requested_engine_version == "0.3.0"
    assert job.configuration_hash == SimulationConfiguration().hash()
    assert job.scenario_id is None
    assert json.loads(job.scenario_spec) == {"schema": "gridwise.scenario/1", "modifications": []}
    # Normal operation: the input is the grid itself, stored once.
    assert job.base_snapshot_id == job.input_snapshot_id
    assert counts(owner_engine) == {"scenarios": 0, "snapshots": 1, "jobs": 1, "job_attempts": 0}

    _, snapshot = await service(app_async_engine).input_snapshot(alpha, job.id)
    assert snapshot.content_hash == job.source_topology_hash == snapshot_hash(snapshot.document)
    assert grid_hash(grid_from_snapshot(snapshot.document)) == grid_hash(sample_grid())


async def test_a_scenario_is_applied_to_a_copy_at_submission(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    scenario_id = await _scenario(
        app_async_engine, alpha, scenario_document(demand_increase(1.5)), "Demand +50 %"
    )
    job = (await service(app_async_engine).submit(alpha, grid_id, scenario_id=scenario_id)).job

    assert job.scenario_id == scenario_id
    assert job.scenario_spec_hash == scenario_hash(demand_increase(1.5))
    assert job.base_snapshot_id != job.input_snapshot_id
    _, snapshot = await service(app_async_engine).input_snapshot(alpha, job.id)
    expected = apply_scenario(sample_grid(), demand_increase(1.5))
    assert snapshot.content_hash == grid_hash(expected)

    # The stored grid is untouched by the scenario.
    async with tenant_transaction(app_async_engine, alpha) as session:
        from gridwise_api.repositories import grids

        stored = await grids.load_grid(session, grid_id)
    assert stored is not None
    assert grid_hash(stored.model) == grid_hash(sample_grid())
    assert counts(owner_engine)["snapshots"] == 2


async def test_identical_snapshots_are_stored_once(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    for _ in range(3):
        await service(app_async_engine).submit(alpha, grid_id)
    assert counts(owner_engine) == {"scenarios": 0, "snapshots": 1, "jobs": 3, "job_attempts": 0}


async def test_a_stale_expected_version_is_refused_and_nothing_is_stored(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    before = counts(owner_engine)
    with pytest.raises(sim.GridVersionConflictError) as raised:
        await service(app_async_engine).submit(alpha, grid_id, expected_grid_version=2)
    assert raised.value.current_version == 1
    assert counts(owner_engine) == before
    job = (await service(app_async_engine).submit(alpha, grid_id, expected_grid_version=1)).job
    assert job.source_grid_version == 1


async def test_a_scenario_naming_missing_elements_is_refused(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    scenario_id = await _scenario(
        app_async_engine,
        alpha,
        {
            "schema": "gridwise.scenario/1",
            "modifications": [{"type": "set_switch", "key": "nowhere", "closed": True}],
        },
    )
    before = counts(owner_engine)
    with pytest.raises(sim.ScenarioNotApplicableError) as raised:
        await service(app_async_engine).submit(alpha, grid_id, scenario_id=scenario_id)
    assert {issue.code for issue in raised.value.issues} == {
        ScenarioErrorCode.SCENARIO_KEY_NOT_FOUND
    }
    assert counts(owner_engine) == before


async def test_a_scenario_that_breaks_the_grid_is_refused(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    scenario_id = await _scenario(
        app_async_engine,
        alpha,
        {
            "schema": "gridwise.scenario/1",
            "modifications": [
                {
                    "type": "set_in_service",
                    "element_type": "external_grid",
                    "key": "upstream",
                    "in_service": False,
                }
            ],
        },
    )
    before = counts(owner_engine)
    with pytest.raises(sim.SimulatedGridInvalidError) as raised:
        await service(app_async_engine).submit(alpha, grid_id, scenario_id=scenario_id)
    assert [issue.code.value for issue in raised.value.issues] == ["missing_external_grid"]
    assert counts(owner_engine) == before


async def test_missing_and_foreign_grids_and_scenarios_are_not_found(
    tenants: dict[str, uuid.UUID], grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    alpha, bravo = tenants["alpha"], tenants["bravo"]
    with pytest.raises(sim.GridNotFoundError):
        await service(app_async_engine).submit(alpha, uuid.uuid4())
    with pytest.raises(sim.GridNotFoundError):
        await service(app_async_engine).submit(bravo, grid_id)  # alpha's grid

    bravo_scenario = await _scenario(app_async_engine, bravo, scenario_document(demand_increase()))
    with pytest.raises(sim.ScenarioNotFoundError):
        await service(app_async_engine).submit(alpha, grid_id, scenario_id=bravo_scenario)


async def test_invalid_scenario_documents_are_refused(
    alpha: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine, migrated: None
) -> None:
    with pytest.raises(sim.ScenarioDocumentInvalidError):
        await _scenario(
            app_async_engine,
            alpha,
            {
                "schema": "gridwise.scenario/1",
                "modifications": [{"type": "scale_loads", "factor": 0}],
            },
        )
    assert counts(owner_engine)["scenarios"] == 0


async def test_scenario_names_are_unique_per_organisation(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    document = scenario_document(demand_increase())
    await _scenario(app_async_engine, tenants["alpha"], document, "Peak")
    with pytest.raises(sim.ScenarioNameConflictError):
        await _scenario(app_async_engine, tenants["alpha"], document, "Peak")
    await _scenario(app_async_engine, tenants["bravo"], document, "Peak")


# --- idempotency --------------------------------------------------------------------------


async def test_the_same_key_and_request_return_the_first_job(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    first = await service(app_async_engine).submit(alpha, grid_id, idempotency_key="run-1")
    again = await service(app_async_engine).submit(alpha, grid_id, idempotency_key="run-1")
    assert (first.created, again.created) == (True, False)
    assert again.job.id == first.job.id
    assert counts(owner_engine)["jobs"] == 1


async def test_the_same_key_for_a_different_request_is_refused(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    await service(app_async_engine).submit(alpha, grid_id, idempotency_key="run-1")
    for changes in (
        {"configuration": SimulationConfiguration(max_iterations=20)},
        {"expected_grid_version": 1},
    ):
        with pytest.raises(sim.IdempotencyKeyReusedError):
            await service(app_async_engine).submit(
                alpha, grid_id, idempotency_key="run-1", **changes
            )
    assert counts(owner_engine)["jobs"] == 1


async def test_concurrent_submissions_with_one_key_make_one_job(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    results = await asyncio.gather(
        *(
            service(app_async_engine).submit(alpha, grid_id, idempotency_key="burst")
            for _ in range(4)
        )
    )
    assert len({result.job.id for result in results}) == 1
    assert sum(result.created for result in results) == 1
    assert counts(owner_engine)["jobs"] == 1


async def test_keys_are_per_organisation(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    alpha_grid = await stored_grid(app_async_engine, tenants["alpha"])
    bravo_grid = await stored_grid(app_async_engine, tenants["bravo"])
    first = await service(app_async_engine).submit(
        tenants["alpha"], alpha_grid, idempotency_key="k"
    )
    second = await service(app_async_engine).submit(
        tenants["bravo"], bravo_grid, idempotency_key="k"
    )
    assert first.job.id != second.job.id
    assert second.created is True


async def test_without_a_key_identical_requests_are_separate_jobs(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    first = await service(app_async_engine).submit(alpha, grid_id)
    second = await service(app_async_engine).submit(alpha, grid_id)
    assert first.job.id != second.job.id
    assert first.job.request_fingerprint == second.job.request_fingerprint
    assert first.job.input_snapshot_id == second.job.input_snapshot_id


# --- the grid while and after it is submitted ---------------------------------------------


async def test_a_grid_write_waits_for_a_submission_in_progress(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, database: TestDatabase
) -> None:
    from gridwise_api.repositories import grids

    grid_service = GridService(app_async_engine, max_elements=5000)
    async with tenant_transaction(app_async_engine, alpha) as session:
        assert await grids.share_lock_grid(session, grid_id) is not None  # a submission's lock
        writer = asyncio.create_task(
            grid_service.update_asset(
                alpha, grid_id, "loads", "load-b", expected_version=1, change=AssetChange(name="x")
            )
        )
        done, _ = await asyncio.wait({writer}, timeout=0.5)
        assert not done  # blocked behind the share lock
    await asyncio.wait_for(writer, timeout=5)  # proceeds once the submission commits


async def test_a_submission_waits_for_a_grid_write_and_captures_its_result(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    from gridwise_api.repositories import grids

    async with tenant_transaction(app_async_engine, alpha) as session:
        await grids.lock_grid(session, grid_id)  # a grid write in progress
        submission = asyncio.create_task(service(app_async_engine).submit(alpha, grid_id))
        done, _ = await asyncio.wait({submission}, timeout=0.5)
        assert not done
        await grids.save_grid_header(
            session, grid_id, version=2, topology_hash=grid_hash(sample_grid())
        )
    job = (await asyncio.wait_for(submission, timeout=5)).job
    assert job.source_grid_version == 2  # never a mix of before and after


async def test_a_job_keeps_its_input_when_the_grid_changes(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    job = (await service(app_async_engine).submit(alpha, grid_id)).job
    before = job_row(owner_engine, job.id)
    await GridService(app_async_engine, max_elements=5000).update_asset(
        alpha, grid_id, "lines", "ab", expected_version=1, change=AssetChange(in_service=False)
    )
    after = job_row(owner_engine, job.id)
    assert after == before
    _, snapshot = await service(app_async_engine).input_snapshot(alpha, job.id)
    assert snapshot.content_hash == grid_hash(sample_grid())


async def test_deleting_the_grid_keeps_the_job_and_its_snapshots(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    from tests.support.simulations import claim, complete

    queued = (await service(app_async_engine).submit(alpha, grid_id)).job
    finished = (await service(app_async_engine).submit(alpha, grid_id)).job
    with owner_engine.begin() as connection:
        claim(connection, finished.id)
        complete(connection, finished.id)

    await GridService(app_async_engine, max_elements=5000).delete(
        alpha, grid_id, expected_version=1
    )

    for job_id in (queued.id, finished.id):
        row = job_row(owner_engine, job_id)
        assert row["source_grid_id"] is None
        assert row["organization_id"] == alpha  # only the reference is cleared
        assert row["source_topology_hash"] == grid_hash(sample_grid())
    assert job_row(owner_engine, finished.id)["status"] == "completed"
    _, snapshot = await service(app_async_engine).input_snapshot(alpha, queued.id)
    assert grid_hash(grid_from_snapshot(snapshot.document)) == grid_hash(sample_grid())


async def test_deleting_the_scenario_keeps_the_jobs_copy(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    scenario_id = await _scenario(app_async_engine, alpha, scenario_document(demand_increase()))
    job = (await service(app_async_engine).submit(alpha, grid_id, scenario_id=scenario_id)).job
    await service(app_async_engine).delete_scenario(alpha, scenario_id)
    row = job_row(owner_engine, job.id)
    assert row["scenario_id"] is None
    assert row["scenario_spec_hash"] == scenario_hash(demand_increase())


# --- cancelling ---------------------------------------------------------------------------


async def test_a_queued_job_can_be_cancelled_once(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    job = (await service(app_async_engine).submit(alpha, grid_id)).job
    cancelled = await service(app_async_engine).cancel(alpha, job.id)
    assert cancelled.status == "cancelled"
    assert cancelled.cancelled_at is not None
    assert cancelled.finished_at == cancelled.cancelled_at
    with pytest.raises(sim.JobNotCancellableError) as raised:
        await service(app_async_engine).cancel(alpha, job.id)
    assert raised.value.status == "cancelled"


async def test_a_running_job_cannot_be_cancelled(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    from tests.support.simulations import claim

    job = (await service(app_async_engine).submit(alpha, grid_id)).job
    with owner_engine.begin() as connection:
        claim(connection, job.id)
    with pytest.raises(sim.JobNotCancellableError):
        await service(app_async_engine).cancel(alpha, job.id)
    assert job_row(owner_engine, job.id)["status"] == "running"


async def test_another_tenants_job_is_not_found(
    tenants: dict[str, uuid.UUID], grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    job = (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job
    for call in (
        service(app_async_engine).cancel(tenants["bravo"], job.id),
        service(app_async_engine).get_job(tenants["bravo"], job.id),
        service(app_async_engine).input_snapshot(tenants["bravo"], job.id),
    ):
        with pytest.raises(sim.JobNotFoundError):
            await call
    details = await service(app_async_engine).get_job(tenants["alpha"], job.id)
    assert details.job.status == "queued"


async def test_jobs_are_listed_newest_first_and_filtered(
    alpha: uuid.UUID, grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    first = (await service(app_async_engine).submit(alpha, grid_id)).job
    second = (await service(app_async_engine).submit(alpha, grid_id)).job
    await service(app_async_engine).cancel(alpha, first.id)
    jobs, total = await service(app_async_engine).list_jobs(alpha, limit=10, offset=0)
    assert [job.id for job in jobs] == [second.id, first.id]
    assert total == 2
    queued, _ = await service(app_async_engine).list_jobs(
        alpha, limit=10, offset=0, status="queued"
    )
    assert [job.id for job in queued] == [second.id]
    by_grid, _ = await service(app_async_engine).list_jobs(
        alpha, limit=10, offset=0, grid_id=uuid.uuid4()
    )
    assert by_grid == []


# --- the boundary -------------------------------------------------------------------------


def test_submitting_never_loads_the_solver(
    tenants: dict[str, uuid.UUID], database: TestDatabase, migrated: None
) -> None:
    """In a fresh interpreter: create a grid, submit it, and check no numerical library
    was ever imported. (This test process has loaded pandapower for other tests.)"""
    code = f"""
import asyncio, sys, uuid
from sqlalchemy.ext.asyncio import create_async_engine
from gridwise_api.repositories import grids
from gridwise_api.services.simulations import SimulationService
from gridwise_api.tenancy import tenant_transaction
from tests.support.grids import sample_grid

async def main():
    engine = create_async_engine({database.app_url!r})
    tenant = uuid.UUID({str(tenants["alpha"])!r})
    async with tenant_transaction(engine, tenant) as session:
        grid = await grids.create_grid(session, sample_grid())
    job = (await SimulationService(engine, max_elements=5000).submit(tenant, grid.id)).job
    await engine.dispose()
    loaded = sorted(m for m in ("pandapower", "pandas", "numpy", "scipy") if m in sys.modules)
    print(job.status, loaded)

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


async def test_a_job_row_cannot_be_inserted_with_another_tenants_snapshot(
    tenants: dict[str, uuid.UUID], grid_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    """The composite foreign key keeps a job's snapshots inside its tenant."""
    from sqlalchemy.exc import IntegrityError

    alpha_job = (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job
    values = {
        field: getattr(alpha_job, field)
        for field in (
            "source_grid_version",
            "source_topology_hash",
            "base_snapshot_id",
            "input_snapshot_id",
            "scenario_spec",
            "scenario_spec_hash",
            "configuration",
            "configuration_hash",
            "requested_engine_version",
            "request_fingerprint",
        )
    }
    with pytest.raises(IntegrityError):
        async with tenant_transaction(app_async_engine, tenants["bravo"]) as session:
            await sim_repository.insert_job(session, values)
