"""Create the synthetic demonstration data: one organisation and one grid.

    python -m gridwise_api.seed [--replace]

What it creates:

* the development organisation, "Development organisation (synthetic)";
* the CIGRE medium-voltage benchmark network with distributed generation, a published
  test network (packages/grid-engine, reference_grids/cigre_mv.py).

Everything here is synthetic. It is not a real network and contains no measured data, and
the grid's name, description and ``data_origin`` say so.

Rules:

* Development environments only. The command reads ``GRIDWISE_ENVIRONMENT`` (it has no
  default here) and refuses anything but ``local`` and ``test``.
* It connects as the owner role (``GRIDWISE_MIGRATION_DATABASE_URL``), like the migration
  runner: only the owner can create an organisation. It never uses the API's credentials.
* Deterministic: fixed organisation and grid ids, element ids derived from them, no random
  numbers and no clock. Two seeded databases hold identical rows (timestamps aside).
* Idempotent: an identical existing grid is left alone. A grid with the same id but other
  content makes the command fail, unless ``--replace`` is given.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from gridwise_api.config import DEVELOPMENT_ENVIRONMENTS, SeedSettings
from gridwise_api.logging import configure_logging, get_logger
from gridwise_api.repositories import grids
from gridwise_api.repositories.grid_mapping import element_keys
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine import GridModel, ensure_valid, grid_hash
from gridwise_grid_engine.reference_grids import cigre_mv

logger = get_logger("gridwise_api.seed")

#: The fixed development tenant. ``GRIDWISE_DEV_ORGANIZATION_ID`` must be set to this value
#: for the API to act for it (see .env.example). Not a secret: it grants nothing by itself.
DEV_ORGANIZATION_ID = UUID("d0000000-0000-4000-8000-000000000001")
DEV_ORGANIZATION_NAME = "Development organisation (synthetic)"
DEV_ORGANIZATION_SLUG = "dev-synthetic"

DEMO_GRID_ID = UUID("d0000000-0000-4000-8000-000000000002")

type Outcome = Literal["created", "unchanged", "replaced"]


class SeedRefusedError(Exception):
    """The command will not run here, or will not overwrite what it found."""


@dataclass(frozen=True, slots=True)
class SeedResult:
    outcome: Outcome
    organization_id: UUID
    grid_id: UUID
    topology_hash: str
    element_count: int


def demo_element_id(table: str, key: str) -> UUID:
    """A row id that depends only on the grid, the element type and the element key."""
    return uuid5(DEMO_GRID_ID, f"{table}:{key}")


def require_development_environment(environment: str) -> None:
    if environment not in DEVELOPMENT_ENVIRONMENTS:
        raise SeedRefusedError(
            f"Refusing to create demonstration data in the {environment!r} environment. "
            "It exists only in local and test."
        )


def _element_count(model: GridModel) -> int:
    return sum(len(keys) for keys in element_keys(model).values())


async def _ensure_organization(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO core.organizations (id, name, slug) VALUES (:id, :name, :slug) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {
                "id": DEV_ORGANIZATION_ID,
                "name": DEV_ORGANIZATION_NAME,
                "slug": DEV_ORGANIZATION_SLUG,
            },
        )


async def seed_demo(engine: AsyncEngine, *, environment: str, replace: bool = False) -> SeedResult:
    """Create the demonstration data. ``engine`` connects as the owner role."""
    require_development_environment(environment)

    model = cigre_mv.cigre_mv_with_der()
    ensure_valid(model)
    expected_hash = grid_hash(model)
    coordinates = dict(cigre_mv.BUS_DIAGRAM_COORDINATES)

    await _ensure_organization(engine)

    async with tenant_transaction(engine, DEV_ORGANIZATION_ID) as session:
        existing = await grids.load_grid(session, DEMO_GRID_ID)
        outcome: Outcome = "created"
        if existing is not None:
            identical = (
                existing.record.topology_hash == expected_hash
                and grid_hash(existing.model) == expected_hash
                and existing.diagram_coordinates == coordinates
                and existing.record.description == cigre_mv.DESCRIPTION
            )
            if identical:
                return SeedResult(
                    "unchanged",
                    DEV_ORGANIZATION_ID,
                    DEMO_GRID_ID,
                    expected_hash,
                    _element_count(model),
                )
            if not replace:
                raise SeedRefusedError(
                    "The demonstration grid exists but differs from the benchmark. "
                    "Run again with --replace to delete it and create it anew."
                )
            await grids.delete_grid(session, DEMO_GRID_ID)
            outcome = "replaced"

        await grids.create_grid(
            session,
            model,
            description=cigre_mv.DESCRIPTION,
            diagram_coordinates=coordinates,
            grid_id=DEMO_GRID_ID,
            element_id=demo_element_id,
        )
    return SeedResult(
        outcome, DEV_ORGANIZATION_ID, DEMO_GRID_ID, expected_hash, _element_count(model)
    )


# SQLSTATEs with a known cause, and what the operator should do about it.
_UNDEFINED_TABLE = "42P01"
_UNDEFINED_SCHEMA = "3F000"
_UNIQUE_VIOLATION = "23505"


def explain_database_error(error: DBAPIError) -> str:
    """One line for the operator. Never the driver's message: it may quote the statement."""
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate in (_UNDEFINED_TABLE, _UNDEFINED_SCHEMA):
        return "The database does not have the grid schema yet. Run `make migrate` first."
    if sqlstate == _UNIQUE_VIOLATION:
        return (
            "Another organisation or grid already uses the demonstration slug, name or id. "
            "Remove it, or start from an empty database (`make reset-db`)."
        )
    if isinstance(error, OperationalError):
        return (
            "Could not reach the database as the owner role. Is it running (`make up`), and "
            "is GRIDWISE_MIGRATION_DATABASE_URL correct?"
        )
    return f"The database refused the operation (SQLSTATE {sqlstate or 'unknown'})."


async def _run(settings: SeedSettings, *, replace: bool) -> SeedResult:
    engine = create_async_engine(
        settings.migration_database_url.get_secret_value(), hide_parameters=True
    )
    try:
        return await seed_demo(engine, environment=settings.environment, replace=replace)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gridwise_api.seed",
        description="Create the synthetic demonstration organisation and grid "
        "(local and test environments only).",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="delete and recreate the demonstration grid if it differs from the benchmark",
    )
    arguments = parser.parse_args(argv)

    settings = SeedSettings()
    configure_logging(settings)
    try:
        # Checked before any connection is opened.
        require_development_environment(settings.environment)
        result = asyncio.run(_run(settings, replace=arguments.replace))
    except SeedRefusedError as error:
        logger.error("seed_refused", reason=str(error))
        return 1
    except DBAPIError as error:
        logger.error(
            "seed_failed",
            reason=explain_database_error(error),
            error_type=type(error.orig).__name__,
            sqlstate=getattr(error.orig, "sqlstate", None),
        )
        return 1
    logger.info(
        "seed_finished",
        outcome=result.outcome,
        organization_id=str(result.organization_id),
        grid_id=str(result.grid_id),
        topology_hash=result.topology_hash,
        elements=result.element_count,
        data_origin="synthetic",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
