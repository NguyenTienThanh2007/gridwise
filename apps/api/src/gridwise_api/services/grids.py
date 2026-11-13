"""Grid rules: what a write must satisfy, and in which order it happens.

Every write runs in one tenant transaction (tenancy.tenant_transaction):

1. lock the grid row (``SELECT ... FOR UPDATE``); not visible -> GridNotFoundError;
2. compare its version with the caller's expected version -> VersionConflictError;
3. build the model that will be stored and validate it with the engine
   -> GridInvalidError, before anything is written;
4. write the change, the new ``topology_hash`` and ``version + 1``;
5. commit. Any exception before the commit rolls everything back.

The service never runs a power flow and never imports the solver adapter. Engine validation
and hashing are plain Python.

There is no authentication. The organisation is whatever the caller passes, which until P6
is the fixed development tenant in local and test environments only.
"""

from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids as repository
from gridwise_api.repositories.grid_mapping import ELEMENT_TABLES, Coordinates, element_keys
from gridwise_api.repositories.grids import GridRecord, StoredGrid
from gridwise_api.tenancy import TenantSession, tenant_transaction
from gridwise_grid_engine import GridModel, ValidationIssue, grid_hash, validate_grid

AssetType = Literal[
    "buses", "lines", "transformers", "loads", "generators", "external_grids", "switches"
]
ASSET_TYPES: tuple[AssetType, ...] = (
    "buses",
    "lines",
    "transformers",
    "loads",
    "generators",
    "external_grids",
    "switches",
)
assert ASSET_TYPES == ELEMENT_TABLES  # noqa: S101  (one list of element types)

#: The engine model's collection for each asset type.
_MODEL_GROUP: dict[AssetType, str] = {name: name for name in ASSET_TYPES}

_NAME_CONSTRAINT = "uq_grids_organization_name"


# --- errors -------------------------------------------------------------------------------


class GridServiceError(Exception):
    """Base class of every failure the service reports deliberately."""


class GridNotFoundError(GridServiceError):
    """The grid does not exist, or belongs to another tenant. Deliberately the same error."""


class AssetNotFoundError(GridServiceError):
    """The grid has no element of this type with this key."""


class VersionConflictError(GridServiceError):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"the grid is at version {current_version}")


class GridInvalidError(GridServiceError):
    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__(f"{len(issues)} validation issue(s)")


class GridNameConflictError(GridServiceError):
    """Another grid of the same organisation has this name."""


class GridTooLargeError(GridServiceError):
    def __init__(self, element_count: int, limit: int) -> None:
        self.element_count = element_count
        self.limit = limit
        super().__init__(f"{element_count} elements, at most {limit} allowed")


# --- results ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class GridSummary:
    record: GridRecord
    element_counts: dict[str, int]


@dataclass(frozen=True, slots=True, kw_only=True)
class AssetChange:
    """A change to one element. Only operating state and name (decision 0007, D3)."""

    name: str | None = None
    #: Every element type except switches.
    in_service: bool | None = None
    #: Switches only.
    closed: bool | None = None


# --- helpers ------------------------------------------------------------------------------


def _is_name_conflict(error: IntegrityError) -> bool:
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == _NAME_CONSTRAINT


def _counts(model: GridModel) -> dict[str, int]:
    return {group: len(keys) for group, keys in element_keys(model).items()}


def _apply_asset_change(
    model: GridModel, asset_type: AssetType, key: str, change: AssetChange
) -> GridModel:
    group = _MODEL_GROUP[asset_type]
    elements = getattr(model, group)
    if not any(element.id == key for element in elements):
        raise AssetNotFoundError
    fields: dict[str, Any] = {}
    if change.name is not None:
        fields["name"] = change.name
    if change.in_service is not None:
        fields["in_service"] = change.in_service
    if change.closed is not None:
        fields["closed"] = change.closed
    changed = tuple(
        replace(element, **fields) if element.id == key else element for element in elements
    )
    return replace(model, **{group: changed})  # type: ignore[arg-type]


# --- the service --------------------------------------------------------------------------


class GridService:
    def __init__(self, engine: AsyncEngine, *, max_elements: int) -> None:
        self._engine = engine
        self._max_elements = max_elements

    def _check(self, model: GridModel) -> None:
        """Everything a model must satisfy before it may be stored."""
        count = sum(_counts(model).values())
        if count > self._max_elements:
            raise GridTooLargeError(count, self._max_elements)
        issues = validate_grid(model)
        if issues:
            raise GridInvalidError(issues)

    async def _lock(
        self, session: TenantSession, grid_id: UUID, expected_version: int
    ) -> GridRecord:
        record = await repository.lock_grid(session, grid_id)
        if record is None:
            raise GridNotFoundError
        if record.version != expected_version:
            raise VersionConflictError(record.version)
        return record

    async def _load_locked(
        self, session: TenantSession, grid_id: UUID, expected_version: int
    ) -> StoredGrid:
        await self._lock(session, grid_id, expected_version)
        stored = await repository.load_grid(session, grid_id)
        if stored is None:  # locked a moment ago in this transaction
            raise GridNotFoundError
        return stored

    # --- reads ---

    async def list(
        self, organization_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[GridSummary], int]:
        async with tenant_transaction(self._engine, organization_id) as session:
            records, total = await repository.list_grids(session, limit=limit, offset=offset)
            counts = await repository.element_counts(session, [record.id for record in records])
        return [
            GridSummary(record=record, element_counts=counts[record.id]) for record in records
        ], total

    async def get(self, organization_id: UUID, grid_id: UUID) -> GridSummary:
        async with tenant_transaction(self._engine, organization_id) as session:
            record = await repository.get_grid(session, grid_id)
            if record is None:
                raise GridNotFoundError
            counts = await repository.element_counts(session, [grid_id])
        return GridSummary(record=record, element_counts=counts[grid_id])

    async def get_topology(self, organization_id: UUID, grid_id: UUID) -> StoredGrid:
        async with tenant_transaction(self._engine, organization_id) as session:
            stored = await repository.load_grid(session, grid_id)
        if stored is None:
            raise GridNotFoundError
        return stored

    # --- writes ---

    async def create(
        self,
        organization_id: UUID,
        model: GridModel,
        *,
        description: str,
        diagram_coordinates: Coordinates,
    ) -> GridSummary:
        """Store a new grid. The model's name is the grid's name."""
        self._check(model)
        try:
            async with tenant_transaction(self._engine, organization_id) as session:
                record = await repository.create_grid(
                    session,
                    model,
                    description=description,
                    diagram_coordinates=diagram_coordinates,
                )
        except IntegrityError as error:
            if _is_name_conflict(error):
                raise GridNameConflictError from error
            raise
        return GridSummary(record=record, element_counts=_counts(model))

    async def update_header(
        self,
        organization_id: UUID,
        grid_id: UUID,
        *,
        expected_version: int,
        name: str | None,
        description: str | None,
    ) -> GridSummary:
        """Rename and/or describe a grid. A rename changes the topology hash."""
        try:
            async with tenant_transaction(self._engine, organization_id) as session:
                stored = await self._load_locked(session, grid_id, expected_version)
                model = stored.model if name is None else replace(stored.model, name=name)
                self._check(model)
                record = await repository.save_grid_header(
                    session,
                    grid_id,
                    version=expected_version + 1,
                    topology_hash=grid_hash(model),
                    name=name,
                    description=description,
                )
        except IntegrityError as error:
            if _is_name_conflict(error):
                raise GridNameConflictError from error
            raise
        return GridSummary(record=record, element_counts=_counts(model))

    async def replace_topology(
        self,
        organization_id: UUID,
        grid_id: UUID,
        *,
        expected_version: int,
        model: GridModel,
        diagram_coordinates: Coordinates,
    ) -> StoredGrid:
        """Replace every element. ``model.name`` is ignored: the grid keeps its name."""
        async with tenant_transaction(self._engine, organization_id) as session:
            record = await self._lock(session, grid_id, expected_version)
            model = replace(model, name=record.name)
            self._check(model)
            await repository.replace_elements(session, grid_id, model, diagram_coordinates)
            await repository.save_grid_header(
                session,
                grid_id,
                version=expected_version + 1,
                topology_hash=grid_hash(model),
                frequency_hz=model.frequency_hz,
            )
            stored = await repository.load_grid(session, grid_id)
        if stored is None:  # pragma: no cover - written in this transaction
            raise GridNotFoundError
        return stored

    async def update_asset(
        self,
        organization_id: UUID,
        grid_id: UUID,
        asset_type: AssetType,
        key: str,
        *,
        expected_version: int,
        change: AssetChange,
    ) -> StoredGrid:
        async with tenant_transaction(self._engine, organization_id) as session:
            stored = await self._load_locked(session, grid_id, expected_version)
            model = _apply_asset_change(stored.model, asset_type, key, change)
            self._check(model)
            values: dict[str, Any] = {
                column: value
                for column, value in (
                    ("name", change.name),
                    ("in_service", change.in_service),
                    ("closed", change.closed),
                )
                if value is not None
            }
            if not await repository.update_element(session, grid_id, asset_type, key, values):
                raise AssetNotFoundError  # pragma: no cover - found in the model above
            await repository.save_grid_header(
                session, grid_id, version=expected_version + 1, topology_hash=grid_hash(model)
            )
            updated = await repository.load_grid(session, grid_id)
        if updated is None:  # pragma: no cover - written in this transaction
            raise GridNotFoundError
        return updated

    async def delete(self, organization_id: UUID, grid_id: UUID, *, expected_version: int) -> None:
        async with tenant_transaction(self._engine, organization_id) as session:
            await self._lock(session, grid_id, expected_version)
            await repository.delete_grid(session, grid_id)


def find_asset(stored: StoredGrid, asset_type: AssetType, key: str) -> Any:
    """The engine element of one asset, or AssetNotFoundError."""
    for element in getattr(stored.model, _MODEL_GROUP[asset_type]):
        if element.id == key:
            return element
    raise AssetNotFoundError


def assets(stored: StoredGrid, asset_type: AssetType) -> tuple[Any, ...]:
    return tuple(getattr(stored.model, _MODEL_GROUP[asset_type]))
