"""Smoke test of the worker as deployed: submit a job, wait for the worker to finish it.

Through the services, as the API would:

    uv run python scripts/worker_smoke.py submit          # prints the job id
    uv run python scripts/worker_smoke.py wait JOB_ID     # exits 0 once it completed

Through the running API over HTTP (decision 0013), the way a client would:

    uv run python scripts/worker_smoke.py http-submit URL               # prints the job id
    uv run python scripts/worker_smoke.py http-wait URL JOB_ID [SECONDS] # 0 once converged
    uv run python scripts/worker_smoke.py http-reproductions URL JOB_ID  # 0 on a "match"

URL is the API's base URL, for example http://localhost:8020.

Uses the root .env (or the environment): GRIDWISE_MIGRATION_DATABASE_URL to seed the
synthetic demonstration grid, GRIDWISE_DATABASE_URL and GRIDWISE_DEV_ORGANIZATION_ID to
submit and read the job as the API would. Local and test environments only. The grid and
its results are synthetic simulations, not measurements.
"""

import asyncio
import sys
import time
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from gridwise_api import seed
from gridwise_api.config import SeedSettings, Settings
from gridwise_api.services.simulations import SimulationService
from gridwise_api.tenancy import resolve_development_tenant, tenant_transaction


async def submit() -> int:
    await _seed()
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


TERMINAL = ("completed", "failed", "cancelled")


async def _seed() -> None:
    seed_settings = SeedSettings()
    owner = create_async_engine(seed_settings.migration_database_url.get_secret_value())
    try:
        await seed.seed_demo(owner, environment=seed_settings.environment)
    finally:
        await owner.dispose()


def http_submit(base_url: str) -> int:
    asyncio.run(_seed())
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.post(f"/api/v1/grids/{seed.DEMO_GRID_ID}/simulations", json={})
        if response.status_code != 202:
            print(f"submit: HTTP {response.status_code}")  # noqa: T201
            return 1
        print(response.json()["id"])  # noqa: T201
    return 0


def http_wait(base_url: str, job_id: UUID, timeout_seconds: float) -> int:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        deadline = time.monotonic() + timeout_seconds
        job = client.get(f"/api/v1/simulations/{job_id}").json()
        while job["status"] not in TERMINAL and time.monotonic() < deadline:
            time.sleep(1)
            job = client.get(f"/api/v1/simulations/{job_id}").json()
        result = client.get(f"/api/v1/simulations/{job_id}/result")
    summary = result.json().get("summary", {}) if result.status_code == 200 else {}
    print(  # noqa: T201
        f"status={job['status']} outcome={job['outcome']} attempt={job['attempt']} "
        f"result=HTTP {result.status_code} converged={summary.get('converged')}"
    )
    converged = (job["status"], job["outcome"], result.status_code) == (
        "completed",
        "converged",
        200,
    )
    return 0 if converged and summary.get("converged") is True else 1


def http_reproductions(base_url: str, job_id: UUID) -> int:
    with httpx.Client(base_url=base_url, timeout=30) as client:
        response = client.get(f"/api/v1/simulations/{job_id}/reproductions")
    verdicts = [item["verdict"] for item in response.json().get("items", [])]
    print(f"reproductions=HTTP {response.status_code} verdicts={verdicts}")  # noqa: T201
    return 0 if response.status_code == 200 and verdicts[:1] == ["match"] else 1


def main() -> int:
    arguments = sys.argv[1:]
    if arguments[:1] == ["submit"]:
        return asyncio.run(submit())
    if len(arguments) >= 2 and arguments[0] == "wait":
        timeout = float(arguments[2]) if len(arguments) > 2 else 120.0
        return asyncio.run(wait(UUID(arguments[1]), timeout))
    if len(arguments) == 2 and arguments[0] == "http-submit":
        return http_submit(arguments[1])
    if len(arguments) >= 3 and arguments[0] == "http-wait":
        timeout = float(arguments[3]) if len(arguments) > 3 else 120.0
        return http_wait(arguments[1], UUID(arguments[2]), timeout)
    if len(arguments) == 3 and arguments[0] == "http-reproductions":
        return http_reproductions(arguments[1], UUID(arguments[2]))
    print(__doc__)  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(main())
