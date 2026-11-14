"""Helpers for simulation tests: a stored grid, a service, and the worker's moves in SQL.

The worker arrives in P1.3b. Until then the tests make its moves directly, as the owner
role (which row-level security does not filter), to exercise the database's lifecycle rules.
"""

import uuid
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids
from gridwise_api.services.simulations import SimulationService
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine import GridModel
from tests.support.grids import sample_grid

SIM_TABLES = ("scenarios", "snapshots", "jobs", "job_attempts")


def service(engine: AsyncEngine) -> SimulationService:
    return SimulationService(engine, max_elements=5000)


async def stored_grid(
    engine: AsyncEngine, organization_id: uuid.UUID, model: GridModel | None = None
) -> uuid.UUID:
    async with tenant_transaction(engine, organization_id) as session:
        record = await grids.create_grid(session, model or sample_grid())
    return record.id


def counts(engine: Engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.execute(text(f"SELECT count(*) FROM sim.{table}")).scalar_one()  # noqa: S608
            for table in SIM_TABLES
        }


def job_row(engine: Engine, job_id: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(text("SELECT * FROM sim.jobs WHERE id = :id"), {"id": job_id})
            .mappings()
            .one()
        )


def claim(connection: Connection, job_id: uuid.UUID, *, worker: str = "worker-1") -> None:
    """queued -> running, as the worker's claim will."""
    connection.execute(
        text(
            "UPDATE sim.jobs SET status = 'running', attempt = attempt + 1, "
            "lease_token = uuidv7(), lease_expires_at = now() + interval '60 seconds', "
            "worker_id = :worker, started_at = now() WHERE id = :id"
        ),
        {"id": job_id, "worker": worker},
    )


def complete(connection: Connection, job_id: uuid.UUID, *, outcome: str = "converged") -> None:
    connection.execute(
        text(
            "UPDATE sim.jobs SET status = 'completed', outcome = :outcome, lease_token = NULL, "
            "lease_expires_at = NULL, worker_id = NULL, finished_at = now(), "
            "executed_engine_version = '0.3.0', solver_name = 'pandapower', "
            "solver_version = '3.5.6', engine_fingerprint = repeat('a', 64) WHERE id = :id"
        ),
        {"id": job_id, "outcome": outcome},
    )


def fail(connection: Connection, job_id: uuid.UUID, *, code: str = "solver_failed") -> None:
    """running -> failed, with the catalogue's message for the code (as the database
    requires since migration 0004)."""
    from gridwise_api.simulation.failures import FAILURE_MESSAGES

    message = {key.value: value for key, value in FAILURE_MESSAGES.items()}.get(code, "unknown")
    connection.execute(
        text(
            "UPDATE sim.jobs SET status = 'failed', failure_code = :code, "
            "failure_message = :message, lease_token = NULL, "
            "lease_expires_at = NULL, worker_id = NULL, finished_at = now() WHERE id = :id"
        ),
        {"id": job_id, "code": code, "message": message},
    )


def requeue(connection: Connection, job_id: uuid.UUID) -> None:
    """running -> queued, as the lease reaper will after a lost worker."""
    connection.execute(
        text(
            "UPDATE sim.jobs SET status = 'queued', lease_token = NULL, lease_expires_at = NULL, "
            "worker_id = NULL WHERE id = :id"
        ),
        {"id": job_id},
    )


def finish_with_real_result(
    worker_engine: Engine,
    *,
    result_hash_override: str | None = None,
    solver_version_override: str | None = None,
) -> uuid.UUID:
    """Claim the oldest job as a worker would and complete it with a real result, computed
    here from the stored input. Overrides simulate a stored result that is not what the
    software computes, or that came from another solver version."""
    from gridwise_grid_engine import __version__, result_hash, run_power_flow
    from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
    from gridwise_grid_engine.fingerprint import engine_fingerprint
    from gridwise_grid_engine.result_documents import result_document_text
    from gridwise_grid_engine.snapshots import grid_from_snapshot
    from gridwise_worker.child import _options
    from gridwise_worker.database import Completion, WorkerDatabase

    database = WorkerDatabase(worker_engine, worker_id="test-finisher", lease_seconds=60)
    lease = database.claim()
    assert lease is not None
    solver = PandapowerSolver()
    options = _options(lease.configuration)
    result = run_power_flow(grid_from_snapshot(lease.input_document), solver, options)
    version = solver_version_override or solver.version
    completion = Completion(
        outcome="converged" if result.converged else "not_converged",
        engine_version=__version__,
        solver_name=solver.name,
        solver_version=version,
        engine_fingerprint=engine_fingerprint(
            engine_version=__version__,
            solver_name=solver.name,
            solver_version=version,
            options=options,
        ),
        result_document=result_document_text(result) if result.converged else None,
        result_hash=(result_hash_override or result_hash(result)) if result.converged else None,
    )
    assert database.complete(lease, completion)
    return lease.job_id
