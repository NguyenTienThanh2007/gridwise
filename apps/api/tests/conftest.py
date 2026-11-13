from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from gridwise_api.config import Settings
from gridwise_api.main import create_app

# Port 1 is never a PostgreSQL server: unit tests must not depend on a database.
UNREACHABLE_DATABASE_URL = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        # Every field the tests rely on is pinned: the developer's environment (for
        # example GRIDWISE_LOG_FORMAT exported by make) must not change test results.
        environment="test",
        log_level="INFO",
        log_format="json",
        database_url=UNREACHABLE_DATABASE_URL,
        readiness_timeout_seconds=1.0,
        cors_origins=["http://localhost:3100"],
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as http_client:
        yield http_client
