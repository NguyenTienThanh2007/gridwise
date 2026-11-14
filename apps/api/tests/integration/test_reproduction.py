"""Reproducing finished jobs: the verdict follows from what is stored, and every check
that can fail does fail when it should. Real solver process, real database, worker role."""

import json
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
from gridwise_grid_engine.scenarios import demand_increase, scenario_document
from gridwise_worker import reproduce
from gridwise_worker.database import WorkerDatabase
from gridwise_worker.supervisor import ChildSupervisor
from tests.integration.conftest import TestDatabase
from tests.support.simulations import (
    claim,
    complete,
    fail,
    finish_with_real_result,
    job_row,
    service,
    stored_grid,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def supervisor() -> Iterator[ChildSupervisor]:
    child = ChildSupervisor()
    child.start()
    yield child
    child.stop()


def _db(worker_engine: Engine) -> WorkerDatabase:
    return WorkerDatabase(worker_engine, worker_id="reproducer", lease_seconds=60)


def _reproduce(
    worker_engine: Engine, supervisor: ChildSupervisor, organization: uuid.UUID, job: uuid.UUID
) -> str | None:
    return reproduce.reproduce_job(
        _db(worker_engine), supervisor, organization, job, timeout_seconds=60
    )


def _reproductions(owner: Engine, job: uuid.UUID) -> list[dict[str, object]]:
    with owner.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM sim.reproductions WHERE job_id = :id ORDER BY created_at"),
                {"id": job},
            ).mappings()
        ]


@pytest.fixture
async def submitted(tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine) -> uuid.UUID:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    return (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job.id


def test_a_correct_result_reproduces(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(worker_engine)
    assert job == submitted
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], job) == "match"
    (record,) = _reproductions(owner_engine, job)
    assert record["verdict"] == "match"
    assert record["reproduced_outcome"] == "converged"
    assert record["solver_name"] == "pandapower"
    assert record["worker_id"] == "reproducer"


def test_a_stored_result_the_software_does_not_compute_is_a_mismatch(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(worker_engine, result_hash_override="0" * 64)
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], job) == "mismatch"


def test_a_difference_after_a_solver_change_is_reported_as_such(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(
        worker_engine, result_hash_override="0" * 64, solver_version_override="0.0.1"
    )
    assert (
        _reproduce(worker_engine, supervisor, tenants["alpha"], job)
        == "differs_after_engine_change"
    )


def test_the_same_result_after_a_solver_change_is_still_a_match(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(worker_engine, solver_version_override="0.0.1")
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], job) == "match"


async def test_non_convergence_reproduces_as_non_convergence(
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    overload = await service(app_async_engine).create_scenario(
        tenants["alpha"],
        name="100x",
        description="",
        document=scenario_document(demand_increase(100)),
    )
    await service(app_async_engine).submit(tenants["alpha"], grid_id, scenario_id=overload.id)
    job = finish_with_real_result(worker_engine)
    assert job_row(owner_engine, job)["outcome"] == "not_converged"
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], job) == "match"
    (record,) = _reproductions(owner_engine, job)
    assert (record["reproduced_outcome"], record["reproduced_result_hash"]) == (
        "not_converged",
        None,
    )


def test_a_converged_job_without_a_result_is_reported_and_not_solved(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    with owner_engine.begin() as connection:  # bypassing complete_job, which would refuse
        claim(connection, submitted)
        complete(connection, submitted)
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], submitted) == "result_missing"
    (record,) = _reproductions(owner_engine, submitted)
    assert record["engine_version"] is None  # nothing was solved


@pytest.mark.parametrize("ending", ["failed", "cancelled"])
def test_jobs_that_did_not_complete_are_not_reproducible(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
    ending: str,
) -> None:
    with owner_engine.begin() as connection:
        if ending == "failed":
            claim(connection, submitted)
            fail(connection, submitted)
        else:
            connection.execute(
                text(
                    "UPDATE sim.jobs SET status = 'cancelled', cancelled_at = now(), "
                    "finished_at = now() WHERE id = :id"
                ),
                {"id": submitted},
            )
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], submitted) == "not_reproducible"


def test_a_damaged_input_is_detected_before_solving(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(worker_engine)
    with owner_engine.begin() as connection:
        # Only possible by removing the database's own protections first.
        connection.execute(text("ALTER TABLE sim.snapshots DISABLE TRIGGER immutable"))
        connection.execute(
            text("ALTER TABLE sim.snapshots DROP CONSTRAINT ck_snapshots_content_hash_matches")
        )
        connection.execute(
            text("UPDATE sim.snapshots SET document = replace(document, '2.0', '2.5')")
        )
    assert _reproduce(worker_engine, supervisor, tenants["alpha"], job) == "snapshot_corrupt"


def test_the_caller_cannot_choose_the_verdict(
    submitted: uuid.UUID, tenants: dict[str, uuid.UUID], worker_engine: Engine, owner_engine: Engine
) -> None:
    """Claiming the stored hash for a failed job still records not_reproducible."""
    with owner_engine.begin() as connection:
        claim(connection, submitted)
        fail(connection, submitted)
    verdict = _db(worker_engine).record_reproduction(
        tenants["alpha"],
        submitted,
        outcome="converged",
        result_hash="a" * 64,
        engine_version="0.3.0",
        solver_name="pandapower",
        solver_version=PandapowerSolver.version,
        problem=None,
    )
    assert verdict == "not_reproducible"
    with pytest.raises(Exception, match="unknown problem"):
        _db(worker_engine).record_reproduction(
            tenants["alpha"],
            submitted,
            outcome=None,
            result_hash=None,
            engine_version=None,
            solver_name=None,
            solver_version=None,
            problem="all good",
        )


def test_reproduction_is_tenant_scoped(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(worker_engine)
    assert _db(worker_engine).reproduction_input(tenants["bravo"], job) is None
    assert _reproduce(worker_engine, supervisor, tenants["bravo"], job) is None
    assert _reproductions(owner_engine, job) == []


async def test_reproductions_are_append_only_and_tenant_readable(
    submitted: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    app_async_engine: AsyncEngine,
    supervisor: ChildSupervisor,
) -> None:
    job = finish_with_real_result(worker_engine)
    _reproduce(worker_engine, supervisor, tenants["alpha"], job)
    async with tenant_transaction(app_async_engine, tenants["alpha"]) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM sim.reproductions"))
        ).scalar_one() == 1
    async with tenant_transaction(app_async_engine, tenants["bravo"]) as session:
        assert (
            await session.execute(text("SELECT count(*) FROM sim.reproductions"))
        ).scalar_one() == 0
    with pytest.raises(Exception, match="immutable"), owner_engine.begin() as connection:
        connection.execute(text("UPDATE sim.reproductions SET verdict = 'match'"))
    with pytest.raises(Exception, match="permission denied"):
        async with tenant_transaction(app_async_engine, tenants["alpha"]) as session:
            await session.execute(text("SELECT * FROM sim.reproduction_candidates(10)"))


async def test_candidates_are_completed_jobs_not_yet_reproduced_across_tenants(
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    worker_engine: Engine,
    supervisor: ChildSupervisor,
) -> None:
    grids = {
        slug: await stored_grid(app_async_engine, tenants[slug]) for slug in ("alpha", "bravo")
    }
    for slug, grid_id in grids.items():
        await service(app_async_engine).submit(tenants[slug], grid_id)
    first, second = finish_with_real_result(worker_engine), finish_with_real_result(worker_engine)
    await service(app_async_engine).submit(tenants["alpha"], grids["alpha"])  # stays queued
    candidates = _db(worker_engine).reproduction_candidates(10)
    assert {job for job, _ in candidates} == {first, second}
    assert {org for _, org in candidates} == {tenants["alpha"], tenants["bravo"]}
    _reproduce(worker_engine, supervisor, tenants["alpha"], first)
    assert [job for job, _ in _db(worker_engine).reproduction_candidates(10)] == [second]


def test_the_command_reports_and_exits_with_the_verdicts(
    submitted: uuid.UUID,
    database: TestDatabase,
    worker_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    finish_with_real_result(worker_engine)
    monkeypatch.setenv("GRIDWISE_WORKER_DATABASE_URL", database.worker_url)
    monkeypatch.setenv("GRIDWISE_LOG_FORMAT", "json")
    assert reproduce.main(["--pending"]) == 0
    lines = [
        json.loads(line) for line in capsys.readouterr().out.splitlines() if '"verdict"' in line
    ]
    assert [line["verdict"] for line in lines] == ["match"]
    assert reproduce.main(["--pending"]) == 0  # nothing left to do


async def test_the_command_exits_non_zero_on_an_integrity_problem(
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    database: TestDatabase,
    worker_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    await service(app_async_engine).submit(tenants["alpha"], grid_id)
    finish_with_real_result(worker_engine, result_hash_override="0" * 64)
    monkeypatch.setenv("GRIDWISE_WORKER_DATABASE_URL", database.worker_url)
    assert reproduce.main(["--pending"]) == 1


def test_a_claim_reports_the_requested_engine_version(
    submitted: uuid.UUID, worker_engine: Engine
) -> None:
    lease = _db(worker_engine).claim()
    assert lease is not None
    assert lease.requested_engine_version == "0.3.0"


def test_worker_connections_have_a_statement_timeout(worker_engine: Engine, migrated: None) -> None:
    from gridwise_worker.database import connect
    from gridwise_worker.settings import WorkerSettings

    settings = WorkerSettings(
        _env_file=None,
        worker_database_url=str(worker_engine.url.render_as_string(hide_password=False)),
    )
    engine = connect(settings)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "30s"
    finally:
        engine.dispose()
