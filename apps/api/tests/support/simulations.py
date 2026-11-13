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
    connection.execute(
        text(
            "UPDATE sim.jobs SET status = 'failed', failure_code = :code, "
            "failure_message = 'catalogue message', lease_token = NULL, "
            "lease_expires_at = NULL, worker_id = NULL, finished_at = now() WHERE id = :id"
        ),
        {"id": job_id, "code": code},
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
