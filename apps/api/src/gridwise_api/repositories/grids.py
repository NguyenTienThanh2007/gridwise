"""Database access for grids and their elements. No business rules live here.

Every function takes a ``TenantSession``: it runs inside a transaction whose tenant context
is set, and it also filters by ``organization_id`` explicitly (docs/decisions/0004), so a
query stays correct even for a role that row-level security does not filter.

This repository does not validate the electrical model and does not decide versions or
hashes. Callers validate with the engine before writing: the seed command, and the grid
service (services/grids.py), which also owns locking, versions and the topology hash.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Table, delete, func, insert, select, text, update

from gridwise_api.models import grid as tables
from gridwise_api.repositories.grid_mapping import (
    ELEMENT_TABLES,
    Coordinates,
    ElementIds,
    assign_ids,
    element_keys,
    model_from_rows,
    rows_from_model,
)
from gridwise_api.tenancy import TenantSession
from gridwise_grid_engine import GridModel, grid_hash

_GRIDS: Table = tables.Grid.__table__  # type: ignore[assignment]
_ELEMENTS: dict[str, Table] = {
    "buses": tables.Bus.__table__,  # type: ignore[dict-item]
    "lines": tables.Line.__table__,  # type: ignore[dict-item]
    "transformers": tables.Transformer.__table__,  # type: ignore[dict-item]
    "loads": tables.Load.__table__,  # type: ignore[dict-item]
    "generators": tables.Generator.__table__,  # type: ignore[dict-item]
    "external_grids": tables.ExternalGrid.__table__,  # type: ignore[dict-item]
    "switches": tables.Switch.__table__,  # type: ignore[dict-item]
}


@dataclass(frozen=True, slots=True, kw_only=True)
class GridRecord:
    id: UUID
    organization_id: UUID
    name: str
    description: str
    frequency_hz: float
    data_origin: str
    version: int
    topology_hash: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredGrid:
    record: GridRecord
    model: GridModel
    diagram_coordinates: dict[str, tuple[float, float]]


class GridVersionConflictError(Exception):
    """The grid was changed by someone else since the caller read it, or does not exist."""


def _record(row: Any) -> GridRecord:
    return GridRecord(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        description=row.description,
        frequency_hz=row.frequency_hz,
        data_origin=row.data_origin,
        version=row.version,
        topology_hash=row.topology_hash,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _allocate_ids(session: TenantSession, count: int) -> list[UUID]:
    """Time-ordered ids from the database, the same kind the column default produces."""
    if count == 0:
        return []
    result = await session.execute(
        text("SELECT uuidv7() FROM generate_series(1, :count)"), {"count": count}
    )
    return list(result.scalars())


async def _database_ids(session: TenantSession, model: GridModel) -> ElementIds:
    keys = element_keys(model)
    allocated = iter(await _allocate_ids(session, sum(len(items) for items in keys.values())))
    return assign_ids(model, lambda _table, _key: next(allocated))


async def create_grid(
    session: TenantSession,
    model: GridModel,
    *,
    description: str = "",
    diagram_coordinates: Coordinates | None = None,
    grid_id: UUID | None = None,
    element_id: Callable[[str, str], UUID] | None = None,
) -> GridRecord:
    """Insert a grid and its whole topology. The caller has validated ``model``.

    ``grid_id`` and ``element_id(table, key)`` let a caller choose the row ids, which the
    seed command uses to be reproducible. Otherwise the database generates them.
    """
    organization_id = session.organization_id
    values: dict[str, Any] = {
        "organization_id": organization_id,
        "name": model.name,
        "description": description,
        "frequency_hz": float(model.frequency_hz),
        "topology_hash": grid_hash(model),
    }
    if grid_id is not None:
        values["id"] = grid_id
    created = (await session.execute(insert(_GRIDS).values(**values).returning(_GRIDS))).one()

    ids = (
        assign_ids(model, element_id)
        if element_id is not None
        else await _database_ids(session, model)
    )
    await _insert_elements(session, model, created.id, ids, diagram_coordinates)
    return _record(created)


async def _insert_elements(
    session: TenantSession,
    model: GridModel,
    grid_id: UUID,
    ids: ElementIds,
    diagram_coordinates: Coordinates | None,
) -> None:
    rows = rows_from_model(
        model,
        organization_id=session.organization_id,
        grid_id=grid_id,
        ids=ids,
        diagram_coordinates=diagram_coordinates,
    )
    # Referenced tables first: buses before what attaches to them, lines and transformers
    # before the switches on them.
    for table in ELEMENT_TABLES:
        if rows[table]:
            await session.execute(insert(_ELEMENTS[table]), rows[table])


async def get_grid(session: TenantSession, grid_id: UUID) -> GridRecord | None:
    row = (
        await session.execute(
            select(_GRIDS).where(
                _GRIDS.c.organization_id == session.organization_id, _GRIDS.c.id == grid_id
            )
        )
    ).one_or_none()
    return _record(row) if row is not None else None


async def load_grid(session: TenantSession, grid_id: UUID) -> StoredGrid | None:
    """The grid with its topology rebuilt as the engine's model."""
    record = await get_grid(session, grid_id)
    if record is None:
        return None
    rows: dict[str, list[dict[str, Any]]] = {}
    for name in ELEMENT_TABLES:
        table = _ELEMENTS[name]
        result = await session.execute(
            select(table).where(
                table.c.organization_id == session.organization_id, table.c.grid_id == grid_id
            )
        )
        rows[name] = [dict(row) for row in result.mappings()]
    model, coordinates = model_from_rows(
        name=record.name, frequency_hz=record.frequency_hz, rows=rows
    )
    return StoredGrid(record=record, model=model, diagram_coordinates=coordinates)


async def delete_grid(session: TenantSession, grid_id: UUID) -> bool:
    """Delete a grid and, by cascade, all of its elements. False if it was not there."""
    result = await session.execute(
        delete(_GRIDS).where(
            _GRIDS.c.organization_id == session.organization_id, _GRIDS.c.id == grid_id
        )
    )
    return result.rowcount == 1


async def claim_version(session: TenantSession, grid_id: UUID, expected_version: int) -> int:
    """Take the next version of a grid, if it is still at ``expected_version``.

    The compare-and-swap of optimistic concurrency (decision 0007, D5). Call it first in
    any transaction that changes a grid or its elements: the update locks the grid row, so
    a second writer waits, then finds the version moved on and gets a conflict.

    Raises:
        GridVersionConflictError: the grid is at another version, or is not visible.
    """
    result = await session.execute(
        update(_GRIDS)
        .where(
            _GRIDS.c.organization_id == session.organization_id,
            _GRIDS.c.id == grid_id,
            _GRIDS.c.version == expected_version,
        )
        .values(version=_GRIDS.c.version + 1)
        .returning(_GRIDS.c.version)
    )
    new_version = result.scalar_one_or_none()
    if new_version is None:
        raise GridVersionConflictError
    return int(new_version)


# --- used by the grid service (P1.2c) ---------------------------------------------------


async def lock_grid(session: TenantSession, grid_id: UUID) -> GridRecord | None:
    """Read a grid and lock its row until the transaction ends (``SELECT ... FOR UPDATE``).

    Every writer to a grid takes this lock first, so writers to one grid are serialised.
    None when the grid does not exist or belongs to another tenant: the two cases are
    indistinguishable here, by design.
    """
    row = (
        await session.execute(
            select(_GRIDS)
            .where(_GRIDS.c.organization_id == session.organization_id, _GRIDS.c.id == grid_id)
            .with_for_update()
        )
    ).one_or_none()
    return _record(row) if row is not None else None


async def save_grid_header(
    session: TenantSession,
    grid_id: UUID,
    *,
    version: int,
    topology_hash: str,
    name: str | None = None,
    description: str | None = None,
    frequency_hz: float | None = None,
) -> GridRecord:
    """Write the grid row's new version and hash, and any changed header fields.

    The caller holds the lock from ``lock_grid`` and has decided ``version`` and
    ``topology_hash``.
    """
    values: dict[str, Any] = {"version": version, "topology_hash": topology_hash}
    if name is not None:
        values["name"] = name
    if description is not None:
        values["description"] = description
    if frequency_hz is not None:
        values["frequency_hz"] = float(frequency_hz)
    row = (
        await session.execute(
            update(_GRIDS)
            .where(_GRIDS.c.organization_id == session.organization_id, _GRIDS.c.id == grid_id)
            .values(**values)
            .returning(_GRIDS)
        )
    ).one()
    return _record(row)


async def replace_elements(
    session: TenantSession,
    grid_id: UUID,
    model: GridModel,
    diagram_coordinates: Coordinates | None,
) -> None:
    """Delete every element of a grid and insert the elements of ``model``.

    Keys are the stable identifiers and are kept; row ids are new. The caller holds the
    grid's lock and writes the header afterwards, in the same transaction.
    """
    # Dependants first: switches reference lines, transformers and buses; everything else
    # references buses.
    for name in reversed(ELEMENT_TABLES):
        table = _ELEMENTS[name]
        await session.execute(
            delete(table).where(
                table.c.organization_id == session.organization_id, table.c.grid_id == grid_id
            )
        )
    ids = await _database_ids(session, model)
    await _insert_elements(session, model, grid_id, ids, diagram_coordinates)


async def update_element(
    session: TenantSession, grid_id: UUID, table_name: str, key: str, values: dict[str, Any]
) -> bool:
    """Change columns of one element, found by its key. False if there is no such element."""
    table = _ELEMENTS[table_name]
    result = await session.execute(
        update(table)
        .where(
            table.c.organization_id == session.organization_id,
            table.c.grid_id == grid_id,
            table.c.key == key,
        )
        .values(**values)
    )
    return result.rowcount == 1


async def list_grids(
    session: TenantSession, *, limit: int, offset: int
) -> tuple[list[GridRecord], int]:
    """A page of the tenant's grids, by name then id, and the total number of grids."""
    tenant = _GRIDS.c.organization_id == session.organization_id
    total = (
        await session.execute(select(func.count()).select_from(_GRIDS).where(tenant))
    ).scalar_one()
    rows = await session.execute(
        select(_GRIDS)
        .where(tenant)
        .order_by(_GRIDS.c.name, _GRIDS.c.id)
        .limit(limit)
        .offset(offset)
    )
    return [_record(row) for row in rows], int(total)


async def element_counts(
    session: TenantSession, grid_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    """Number of elements of each type, per grid. Grids without elements of a type get 0."""
    counts = {grid_id: dict.fromkeys(ELEMENT_TABLES, 0) for grid_id in grid_ids}
    if not grid_ids:
        return counts
    for name in ELEMENT_TABLES:
        table = _ELEMENTS[name]
        rows = await session.execute(
            select(table.c.grid_id.label("grid_id"), func.count().label("count"))
            .where(
                table.c.organization_id == session.organization_id,
                table.c.grid_id.in_(grid_ids),
            )
            .group_by(table.c.grid_id)
        )
        for row in rows.mappings():
            counts[row["grid_id"]][name] = int(row["count"])
    return counts
