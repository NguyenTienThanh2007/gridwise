"""Retention: only finished jobs before the cutoff go, with everything that is theirs alone."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api import retention
from gridwise_worker import reproduce
from gridwise_worker.database import WorkerDatabase
from gridwise_worker.supervisor import ChildSupervisor
from tests.integration.conftest import TestDatabase
from tests.support.api import database_snapshot
from tests.support.simulations import claim, finish_with_real_result, job_row, service, stored_grid

pytestmark = pytest.mark.integration

LATER = datetime.now(UTC) + timedelta(days=1)


def _count(owner: Engine, table: str) -> int:
    with owner.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # type: ignore[no-any-return]  # noqa: S608


@pytest.fixture
async def world(
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    worker_engine: Engine,
    owner_engine: Engine,
) -> dict[str, uuid.UUID]:
    """alpha: one finished and reproduced job, one queued and one running job, all on one
    grid (so they share snapshots). bravo: one finished job."""
    grid = await stored_grid(app_async_engine, tenants["alpha"])
    await service(app_async_engine).submit(tenants["alpha"], grid)
    finished = finish_with_real_result(worker_engine)
    supervisor = ChildSupervisor()
    try:
        reproduce.reproduce_job(
            WorkerDatabase(worker_engine, worker_id="r", lease_seconds=60),
            supervisor,
            tenants["alpha"],
            finished,
            timeout_seconds=60,
        )
    finally:
        supervisor.stop()
    # bravo's job is finished before alpha's queued and running ones exist: the helper
    # finishes the oldest queued job.
    bravo_grid = await stored_grid(app_async_engine, tenants["bravo"])
    await service(app_async_engine).submit(tenants["bravo"], bravo_grid)
    bravo_finished = finish_with_real_result(worker_engine)
    queued = (await service(app_async_engine).submit(tenants["alpha"], grid)).job.id
    running = (await service(app_async_engine).submit(tenants["alpha"], grid)).job.id
    with owner_engine.begin() as connection:
        claim(connection, running)
    return {
        "alpha_grid": grid,
        "finished": finished,
        "queued": queued,
        "running": running,
        "bravo_finished": bravo_finished,
    }


async def test_a_dry_run_reports_and_changes_nothing(
    world: dict[str, uuid.UUID], owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    before = database_snapshot(owner_engine)
    report = await retention.apply_retention(owner_async_engine, finished_before=LATER)
    assert report.applied is False
    assert (report.jobs, report.results, report.reproductions) == (2, 2, 1)
    assert report.attempts == 2
    # alpha's snapshot is still used by its queued and running jobs; bravo's is not.
    assert report.snapshots == 1
    assert database_snapshot(owner_engine) == before


async def test_applying_deletes_only_finished_jobs_and_what_is_theirs_alone(
    world: dict[str, uuid.UUID], owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    report = await retention.apply_retention(owner_async_engine, finished_before=LATER, apply=True)
    assert (report.jobs, report.results, report.reproductions, report.snapshots) == (2, 2, 1, 1)
    with owner_engine.connect() as connection:
        remaining = set(connection.execute(text("SELECT id FROM sim.jobs")).scalars())
    assert remaining == {world["queued"], world["running"]}
    assert job_row(owner_engine, world["running"])["status"] == "running"
    assert _count(owner_engine, "sim.results") == 0
    assert _count(owner_engine, "sim.reproductions") == 0
    assert _count(owner_engine, "sim.snapshots") == 1  # alpha's, still in use
    assert _count(owner_engine, "grid.grids") == 2  # grids are never touched
    again = await retention.apply_retention(owner_async_engine, finished_before=LATER, apply=True)
    assert again.jobs == 0


async def test_the_cutoff_and_the_organisation_filter(
    world: dict[str, uuid.UUID],
    tenants: dict[str, uuid.UUID],
    owner_async_engine: AsyncEngine,
    owner_engine: Engine,
) -> None:
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    report = await retention.apply_retention(
        owner_async_engine, finished_before=long_ago, apply=True
    )
    assert report.jobs == 0
    report = await retention.apply_retention(
        owner_async_engine, finished_before=LATER, organization_id=tenants["bravo"], apply=True
    )
    assert report.jobs == 1
    with owner_engine.connect() as connection:
        ids = set(connection.execute(text("SELECT id FROM sim.jobs")).scalars())
    assert world["finished"] in ids
    assert world["bravo_finished"] not in ids


async def test_a_failure_rolls_back_that_jobs_deletion(
    world: dict[str, uuid.UUID], owner_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                f"""
                CREATE FUNCTION sim.test_refuse() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF OLD.job_id = '{world["finished"]}' THEN
                        RAISE EXCEPTION 'refused' USING ERRCODE = 'foreign_key_violation';
                    END IF;
                    RETURN OLD;
                END $$;
                CREATE TRIGGER test_refuse BEFORE DELETE ON sim.results
                FOR EACH ROW EXECUTE FUNCTION sim.test_refuse();
                """
            )
        )
    report = await retention.apply_retention(owner_async_engine, finished_before=LATER, apply=True)
    assert (report.jobs, report.skipped) == (1, 1)
    row = job_row(owner_engine, world["finished"])
    assert row["status"] == "completed"
    with owner_engine.connect() as connection:
        kept = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM sim.job_attempts WHERE job_id = :id), "
                "(SELECT count(*) FROM sim.reproductions WHERE job_id = :id)"
            ),
            {"id": world["finished"]},
        ).one()
    assert tuple(kept) == (1, 1)  # nothing of it was deleted


def test_the_command_needs_a_time_zone_and_is_a_dry_run_by_default(
    world: dict[str, uuid.UUID],
    database: TestDatabase,
    owner_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json

    monkeypatch.setenv("GRIDWISE_MIGRATION_DATABASE_URL", database.owner_url)
    monkeypatch.setenv("GRIDWISE_LOG_FORMAT", "json")
    with pytest.raises(SystemExit):
        retention.main(["--finished-before", "2026-01-01T00:00:00"])
    before = database_snapshot(owner_engine)
    assert retention.main(["--finished-before", LATER.isoformat()]) == 0
    output = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")][-1]
    assert json.loads(output)["applied"] is False
    assert database_snapshot(owner_engine) == before
