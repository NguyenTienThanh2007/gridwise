"""The ``sim`` schema: scenarios, immutable input snapshots, simulation jobs and attempts.

These classes describe columns, keys and indexes, which the model-drift test compares with
the database. Row checks, triggers and the two column-list foreign keys
(``ON DELETE SET NULL (column)``) live in migration 0003 only.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gridwise_api.models.base import Base

SCHEMA = "sim"


def _tenant_keys(
    table: str,
) -> tuple[PrimaryKeyConstraint | UniqueConstraint | ForeignKeyConstraint, ...]:
    return (
        PrimaryKeyConstraint("id", name=f"pk_{table}"),
        UniqueConstraint("organization_id", "id", name=f"uq_{table}_organization_id"),
        ForeignKeyConstraint(
            ["organization_id"], ["core.organizations.id"], name=f"fk_{table}_organization"
        ),
    )


class JobTransition(Base):
    """Reference data: the legal status moves (gridwise_api.simulation.states)."""

    __tablename__ = "job_transitions"
    __table_args__ = (
        PrimaryKeyConstraint("from_status", "to_status", name="pk_job_transitions"),
        {"schema": SCHEMA},
    )

    from_status: Mapped[str] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (
        *_tenant_keys("scenarios"),
        UniqueConstraint("organization_id", "name", name="uq_scenarios_organization_name"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, server_default=text("uuidv7()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    spec: Mapped[str] = mapped_column(Text)
    spec_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        *_tenant_keys("snapshots"),
        UniqueConstraint(
            "organization_id", "content_hash", name="uq_snapshots_organization_content_hash"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, server_default=text("uuidv7()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    document_schema: Mapped[str] = mapped_column(Text, server_default=text("'gridwise.grid/2'"))
    element_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        *_tenant_keys("jobs"),
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_jobs_organization_idempotency_key"
        ),
        ForeignKeyConstraint(
            ["organization_id", "base_snapshot_id"],
            ["sim.snapshots.organization_id", "sim.snapshots.id"],
            name="fk_jobs_base_snapshot",
        ),
        ForeignKeyConstraint(
            ["organization_id", "input_snapshot_id"],
            ["sim.snapshots.organization_id", "sim.snapshots.id"],
            name="fk_jobs_input_snapshot",
        ),
        # Both clear only their own column (PostgreSQL 15+ column-list form), so the job
        # keeps its organization_id. Written exactly as PostgreSQL reports it, so the drift
        # test compares it; these models are never used to create tables.
        ForeignKeyConstraint(
            ["organization_id", "source_grid_id"],
            ["grid.grids.organization_id", "grid.grids.id"],
            name="fk_jobs_source_grid",
            ondelete="SET NULL (source_grid_id)",
        ),
        ForeignKeyConstraint(
            ["organization_id", "scenario_id"],
            ["sim.scenarios.organization_id", "sim.scenarios.id"],
            name="fk_jobs_scenario",
            ondelete="SET NULL (scenario_id)",
        ),
        ForeignKeyConstraint(
            ["failure_code", "failure_message"],
            ["sim.failure_catalogue.code", "sim.failure_catalogue.message"],
            name="fk_jobs_failure",
        ),
        Index("ix_jobs_organization_status_created", "organization_id", "status", "created_at"),
        Index("ix_jobs_queued", "created_at", "id", postgresql_where=text("status = 'queued'")),
        Index(
            "ix_jobs_running_lease", "lease_expires_at", postgresql_where=text("status = 'running'")
        ),
        Index("ix_jobs_source_grid_id", "source_grid_id"),
        Index("ix_jobs_scenario_id", "scenario_id"),
        Index("ix_jobs_base_snapshot_id", "base_snapshot_id"),
        Index("ix_jobs_input_snapshot_id", "input_snapshot_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, server_default=text("uuidv7()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_grid_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source_grid_version: Mapped[int] = mapped_column(Integer)
    source_topology_hash: Mapped[str] = mapped_column(Text)
    base_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    input_snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    scenario_spec: Mapped[str] = mapped_column(Text)
    scenario_spec_hash: Mapped[str] = mapped_column(Text)
    configuration: Mapped[str] = mapped_column(Text)
    configuration_hash: Mapped[str] = mapped_column(Text)
    requested_engine_version: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("3"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    outcome: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_message: Mapped[str | None] = mapped_column(Text)
    executed_engine_version: Mapped[str | None] = mapped_column(Text)
    solver_name: Mapped[str | None] = mapped_column(Text)
    solver_version: Mapped[str | None] = mapped_column(Text)
    engine_fingerprint: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Maintained by the lifecycle trigger.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), server_onupdate=FetchedValue()
    )


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        *_tenant_keys("job_attempts"),
        UniqueConstraint(
            "organization_id", "job_id", "attempt", name="uq_job_attempts_organization_job_attempt"
        ),
        ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["sim.jobs.organization_id", "sim.jobs.id"],
            name="fk_job_attempts_job",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, server_default=text("uuidv7()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    attempt: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[str | None] = mapped_column(Text)


class FailureCatalogue(Base):
    """Reference data: the only failure codes and messages there are."""

    __tablename__ = "failure_catalogue"
    __table_args__ = (
        PrimaryKeyConstraint("code", name="pk_failure_catalogue"),
        UniqueConstraint("code", "message", name="uq_failure_catalogue_code_message"),
        {"schema": SCHEMA},
    )

    code: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)


class Result(Base):
    """The result of one converged job, as the engine computed it. Written only by
    sim.complete_job, never changed."""

    __tablename__ = "results"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_results"),
        UniqueConstraint("organization_id", "job_id", name="uq_results_organization_job"),
        ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["sim.jobs.organization_id", "sim.jobs.id"],
            name="fk_results_job",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, server_default=text("uuidv7()"))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document: Mapped[str] = mapped_column(Text)
    document_hash: Mapped[str] = mapped_column(Text)
    result_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
