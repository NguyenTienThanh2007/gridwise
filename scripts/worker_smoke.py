"""Smoke test of the worker as deployed: submit a job, wait for the worker to finish it.

    uv run python scripts/worker_smoke.py submit          # prints the job id
    uv run python scripts/worker_smoke.py wait JOB_ID     # exits 0 once it completed

Uses the root .env (or the environment): GRIDWISE_MIGRATION_DATABASE_URL to seed the
synthetic demonstration grid, GRIDWISE_DATABASE_URL and GRIDWISE_DEV_ORGANIZATION_ID to
submit and read the job as the API would. Local and test environments only.
"""

import asyncio
import sys
import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gridwise_api import seed
from gridwise_api.config import SeedSettings, Settings
from gridwise_api.services.simulations import SimulationService
from gridwise_api.tenancy import resolve_development_tenant, tenant_transaction


async def submit() -> int:
    seed_settings = SeedSettings()
    owner = create_async_engine(seed_settings.migration_database_url.get_secret_value())
    try:
        await seed.seed_demo(owner, environment=seed_settings.environment)
    finally:
        await owner.dispose()
    settings = Settings()
    tenant = resolve_development_tenant(settings)
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        job = (
            await SimulationService(engine, max_elements=5000).submit(tenant, seed.DEMO_GRID_ID)
        ).job
    finally:
        await engine.dispose()
    print(job.id)  # noqa: T201
    return 0


async def wait(job_id: UUID, timeout_seconds: float) -> int:
    settings = Settings()
    tenant = resolve_development_tenant(settings)
    engine = create_async_engine(settings.database_url.get_secret_value())
    service = SimulationService(engine, max_elements=5000)
    try:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = (await service.get_job(tenant, job_id)).job
            if job.status in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(1)
        async with tenant_transaction(engine, tenant) as session:
            results = (
                await session.execute(
                    text("SELECT count(*) FROM sim.results WHERE job_id = :id"), {"id": job_id}
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    print(f"status={job.status} outcome={job.outcome} attempt={job.attempt} results={results}")  # noqa: T201
    return 0 if (job.status, job.outcome, results) == ("completed", "converged", 1) else 1


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "submit":
        return asyncio.run(submit())
    if len(sys.argv) >= 3 and sys.argv[1] == "wait":
        timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
        return asyncio.run(wait(UUID(sys.argv[2]), timeout))
    print(__doc__)  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(main())
