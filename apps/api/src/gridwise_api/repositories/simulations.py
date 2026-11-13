"""Database access for scenarios, snapshots and simulation jobs. No business rules here.

Every function takes a ``TenantSession`` and also filters by ``organization_id`` itself
(decision 0004). The rules about what may be submitted live in services/simulations.py;
the rules about how a job may change live in the database (migration 0003).
"""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Table, delete, func, insert, select, text, update

from gridwise_api.models import simulation as tables
from gridwise_api.tenancy import TenantSession

_SCENARIOS: Table = tables.Scenario.__table__  # type: ignore[assignment]
_SNAPSHOTS: Table = tables.Snapshot.__table__  # type: ignore[assignment]
_JOBS: Table = tables.Job.__table__  # type: ignore[assignment]
_ATTEMPTS: Table = tables.JobAttempt.__table__  # type: ignore[assignment]


class SnapshotContentMismatchError(Exception):
    """A stored snapshot has the same hash as new content but different text."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRecord:
    id: UUID
    organization_id: UUID
    name: str
    description: str
    spec: str
    spec_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotRecord:
    id: UUID
    organization_id: UUID
    document: str
    content_hash: str
    element_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class JobRecord:
    id: UUID
    organization_id: UUID
    source_grid_id: UUID | None
    source_grid_version: int
    source_topology_hash: str
    base_snapshot_id: UUID
    input_snapshot_id: UUID
    scenario_id: UUID | None
    scenario_spec: str
    scenario_spec_hash: str
    configuration: str
    configuration_hash: str
    requested_engine_version: str
    idempotency_key: str | None
    request_fingerprint: str
    max_attempts: int
    status: str
    outcome: str | None
    attempt: int
    failure_code: str | None
    failure_message: str | None
    executed_engine_version: str | None
    solver_name: str | None
    solver_version: str | None
    engine_fingerprint: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancelled_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptRecord:
    attempt: int
    worker_id: str
    started_at: datetime
    ended_at: datetime | None
    ended_by: str | None


def _fields(record_type: type, row: Any) -> Any:
    mapping = row._mapping
    return record_type(**{field.name: mapping[field.name] for field in fields(record_type)})


# --- scenarios ----------------------------------------------------------------------------


async def insert_scenario(
    session: TenantSession, *, name: str, description: str, spec: str, spec_hash: str
) -> ScenarioRecord:
    row = (
        await session.execute(
            insert(_SCENARIOS)
            .values(
                organization_id=session.organization_id,
                name=name,
                description=description,
                spec=spec,
                spec_hash=spec_hash,
            )
            .returning(_SCENARIOS)
        )
    ).one()
    return _fields(ScenarioRecord, row)  # type: ignore[no-any-return]


async def get_scenario(session: TenantSession, scenario_id: UUID) -> ScenarioRecord | None:
    row = (
        await session.execute(
            select(_SCENARIOS).where(
                _SCENARIOS.c.organization_id == session.organization_id,
                _SCENARIOS.c.id == scenario_id,
            )
        )
    ).one_or_none()
    return _fields(ScenarioRecord, row) if row is not None else None


async def list_scenarios(
    session: TenantSession, *, limit: int, offset: int
) -> tuple[list[ScenarioRecord], int]:
    tenant = _SCENARIOS.c.organization_id == session.organization_id
    total = (
        await session.execute(select(func.count()).select_from(_SCENARIOS).where(tenant))
    ).scalar_one()
    rows = await session.execute(
        select(_SCENARIOS)
        .where(tenant)
        .order_by(_SCENARIOS.c.name, _SCENARIOS.c.id)
        .limit(limit)
        .offset(offset)
    )
    return [_fields(ScenarioRecord, row) for row in rows], int(total)


async def delete_scenario(session: TenantSession, scenario_id: UUID) -> bool:
    result = await session.execute(
        delete(_SCENARIOS).where(
            _SCENARIOS.c.organization_id == session.organization_id,
            _SCENARIOS.c.id == scenario_id,
        )
    )
    return result.rowcount == 1


# --- snapshots ----------------------------------------------------------------------------


async def store_snapshot(
    session: TenantSession, *, document: str, content_hash: str, element_count: int
) -> UUID:
    """The id of the snapshot with this content, stored now if it was not stored yet.

    Snapshots are deduplicated per tenant by hash. An existing row must hold exactly this
    text; anything else would be a hash collision or a damaged row, and is refused.
    """
    inserted = (
        await session.execute(
            text(
                "INSERT INTO sim.snapshots (organization_id, document, content_hash, "
                "element_count) VALUES (:organization_id, :document, :content_hash, "
                ":element_count) ON CONFLICT (organization_id, content_hash) DO NOTHING "
                "RETURNING id"
            ),
            {
                "organization_id": session.organization_id,
                "document": document,
                "content_hash": content_hash,
                "element_count": element_count,
            },
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted  # type: ignore[no-any-return]
    existing = (
        await session.execute(
            select(_SNAPSHOTS.c.id, _SNAPSHOTS.c.document).where(
                _SNAPSHOTS.c.organization_id == session.organization_id,
                _SNAPSHOTS.c.content_hash == content_hash,
            )
        )
    ).one()
    if existing.document != document:
        raise SnapshotContentMismatchError
    return existing.id  # type: ignore[no-any-return]


async def get_snapshot(session: TenantSession, snapshot_id: UUID) -> SnapshotRecord | None:
    row = (
        await session.execute(
            select(_SNAPSHOTS).where(
                _SNAPSHOTS.c.organization_id == session.organization_id,
                _SNAPSHOTS.c.id == snapshot_id,
            )
        )
    ).one_or_none()
    return _fields(SnapshotRecord, row) if row is not None else None


# --- jobs ---------------------------------------------------------------------------------


async def insert_job(session: TenantSession, values: dict[str, Any]) -> JobRecord:
    row = (
        await session.execute(
            insert(_JOBS).values(organization_id=session.organization_id, **values).returning(_JOBS)
        )
    ).one()
    return _fields(JobRecord, row)  # type: ignore[no-any-return]


async def get_job(session: TenantSession, job_id: UUID) -> JobRecord | None:
    row = (
        await session.execute(
            select(_JOBS).where(
                _JOBS.c.organization_id == session.organization_id, _JOBS.c.id == job_id
            )
        )
    ).one_or_none()
    return _fields(JobRecord, row) if row is not None else None


async def find_job_by_idempotency_key(session: TenantSession, key: str) -> JobRecord | None:
    row = (
        await session.execute(
            select(_JOBS).where(
                _JOBS.c.organization_id == session.organization_id,
                _JOBS.c.idempotency_key == key,
            )
        )
    ).one_or_none()
    return _fields(JobRecord, row) if row is not None else None


async def list_jobs(
    session: TenantSession,
    *,
    limit: int,
    offset: int,
    grid_id: UUID | None = None,
    status: str | None = None,
) -> tuple[list[JobRecord], int]:
    conditions = [_JOBS.c.organization_id == session.organization_id]
    if grid_id is not None:
        conditions.append(_JOBS.c.source_grid_id == grid_id)
    if status is not None:
        conditions.append(_JOBS.c.status == status)
    total = (
        await session.execute(select(func.count()).select_from(_JOBS).where(*conditions))
    ).scalar_one()
    rows = await session.execute(
        select(_JOBS)
        .where(*conditions)
        .order_by(_JOBS.c.created_at.desc(), _JOBS.c.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_fields(JobRecord, row) for row in rows], int(total)


async def cancel_queued_job(session: TenantSession, job_id: UUID) -> JobRecord | None:
    """Cancel a job if it is still queued. None if it is not (or does not exist)."""
    row = (
        await session.execute(
            update(_JOBS)
            .where(
                _JOBS.c.organization_id == session.organization_id,
                _JOBS.c.id == job_id,
                _JOBS.c.status == "queued",
            )
            .values(status="cancelled", cancelled_at=func.now(), finished_at=func.now())
            .returning(_JOBS)
        )
    ).one_or_none()
    return _fields(JobRecord, row) if row is not None else None


async def list_attempts(session: TenantSession, job_id: UUID) -> list[AttemptRecord]:
    rows = await session.execute(
        select(_ATTEMPTS)
        .where(
            _ATTEMPTS.c.organization_id == session.organization_id,
            _ATTEMPTS.c.job_id == job_id,
        )
        .order_by(_ATTEMPTS.c.attempt)
    )
    return [_fields(AttemptRecord, row) for row in rows]
