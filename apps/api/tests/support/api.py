"""Helpers for testing the grid API over HTTP, as deployed: through the app, as the runtime
role, against a real PostgreSQL database."""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Engine, text

from gridwise_api.api.schemas.grid_mapping import topology_from_model
from gridwise_api.config import Settings
from gridwise_api.main import create_app
from gridwise_grid_engine import GridModel
from tests.support.grids import GRID_TABLES


def topology_payload(
    model: GridModel, coordinates: Mapping[str, tuple[float, float]] | None = None
) -> dict[str, Any]:
    return topology_from_model(model, coordinates or {}).model_dump(mode="json")


def create_payload(
    model: GridModel,
    coordinates: Mapping[str, tuple[float, float]] | None = None,
    *,
    description: str = "",
) -> dict[str, Any]:
    return {
        "name": model.name,
        "description": description,
        "topology": topology_payload(model, coordinates),
    }


@asynccontextmanager
async def grid_api(
    database_url: str, organization_id: UUID | None, **settings: Any
) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client for an app acting for ``organization_id`` (the development tenant)."""
    app = create_app(
        Settings(
            _env_file=None,
            environment=settings.pop("environment", "test"),
            log_format="json",
            log_level="WARNING",
            database_url=database_url,
            dev_organization_id=organization_id,
            **settings,
        )
    )
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            yield client
    finally:
        await app.state.engine.dispose()


def database_snapshot(engine: Engine) -> dict[str, list[str]]:
    """Every row of every grid table, everything included (ids, versions, timestamps)."""
    snapshot = {}
    with engine.connect() as connection:
        for table in GRID_TABLES:
            snapshot[table] = list(
                connection.execute(
                    text(f"SELECT to_jsonb(t)::text FROM grid.{table} t ORDER BY id")  # noqa: S608
                ).scalars()
            )
    return snapshot


def without_request_id(body: dict[str, Any]) -> dict[str, Any]:
    error = dict(body["error"])
    error.pop("request_id", None)
    return {"error": error}
