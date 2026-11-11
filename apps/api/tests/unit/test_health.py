import asyncio
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError, ProgrammingError

from gridwise_api.api.dependencies import get_health_service
from gridwise_api.schema_version import EXPECTED_SCHEMA_REVISION
from gridwise_api.services.health import HealthService

EXPECTED = "0007"  # arbitrary: these tests must not depend on the real head


class FakeSystemRepository:
    def __init__(
        self,
        *,
        revision: str | None = EXPECTED,
        ping_error: Exception | None = None,
        revision_error: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self._revision = revision
        self._ping_error = ping_error
        self._revision_error = revision_error
        self._delay_seconds = delay_seconds

    async def ping(self) -> None:
        await asyncio.sleep(self._delay_seconds)
        if self._ping_error is not None:
            raise self._ping_error

    async def schema_revision(self) -> str | None:
        if self._revision_error is not None:
            raise self._revision_error
        return self._revision


def use_repository(app: FastAPI, repository: FakeSystemRepository, timeout: float = 1.0) -> None:
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        repository, timeout_seconds=timeout, expected_revision=EXPECTED
    )


async def test_live_does_not_need_a_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_when_database_is_reachable_and_at_the_expected_revision(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_repository(app, FakeSystemRepository(revision=EXPECTED))
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ok",
        "schema_revision": EXPECTED,
        "expected_schema_revision": EXPECTED,
    }


async def test_not_ready_when_database_is_down(app: FastAPI, client: httpx.AsyncClient) -> None:
    error = OperationalError("SELECT 1", {}, Exception("connection refused"))
    use_repository(app, FakeSystemRepository(ping_error=error))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "unavailable",
        "schema_revision": None,
        "expected_schema_revision": EXPECTED,
    }


async def test_not_ready_when_schema_was_never_migrated(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_repository(app, FakeSystemRepository(revision=None))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "not_migrated"


@pytest.mark.parametrize("applied", ["0006", "0008"], ids=["behind", "ahead"])
async def test_not_ready_when_schema_is_behind_or_ahead(
    app: FastAPI, client: httpx.AsyncClient, applied: str
) -> None:
    use_repository(app, FakeSystemRepository(revision=applied))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "schema_mismatch",
        "schema_revision": applied,
        "expected_schema_revision": EXPECTED,
    }


async def test_a_database_fault_while_reading_the_revision_is_not_called_a_migration_problem(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    error = ProgrammingError("SELECT", {}, Exception("permission denied for table"))
    use_repository(app, FakeSystemRepository(revision_error=error))
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


async def test_not_ready_when_database_is_slower_than_the_timeout(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    use_repository(app, FakeSystemRepository(delay_seconds=5.0), timeout=0.05)
    response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


async def test_real_repository_reports_unreachable_database(client: httpx.AsyncClient) -> None:
    """No override: the SQL repository itself, pointed at a port nothing listens on."""
    response = await client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["database"] == "unavailable"
    assert body["expected_schema_revision"] == EXPECTED_SCHEMA_REVISION


def test_expected_revision_is_the_packaged_migration_head() -> None:
    """Adding a migration without bumping EXPECTED_SCHEMA_REVISION must fail here."""
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_SCHEMA_REVISION]
