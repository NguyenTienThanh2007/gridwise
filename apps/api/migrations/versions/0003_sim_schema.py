"""Simulation schema: scenarios, immutable input snapshots, jobs and their attempts.

Tables (all tenant-owned, with row-level security like the grid schema):

* ``scenarios``    named scenario documents. Immutable: no row is ever updated.
* ``snapshots``    the exact input of simulations, as canonical text. Immutable for every
                   role, and the database itself checks that ``content_hash`` is the SHA-256
                   of ``document``.
* ``jobs``         one simulation each. What was submitted never changes; the lifecycle
                   follows ``job_transitions`` and is enforced by a trigger for every role.
* ``job_attempts`` one row per time a worker took the job: the record of every retry.

``job_transitions`` is reference data (the legal status moves), not tenant data.

Results (P1.3c) and the worker's role and claim function (P1.3b) come in later migrations.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "gridwise_app"
SCHEMA = "sim"
TENANT_TABLES = ("scenarios", "snapshots", "jobs", "job_attempts")

STATUSES = ("queued", "running", "completed", "failed", "cancelled")
TRANSITIONS = (
    ("queued", "running"),
    ("queued", "cancelled"),
    ("running", "running"),
    ("running", "completed"),
    ("running", "failed"),
    ("running", "queued"),
)
OUTCOMES = ("converged", "not_converged")
FAILURE_CODES = (
    "solver_failed",
    "inconsistent_solution",
    "execution_timeout",
    "worker_lost",
    "snapshot_corrupt",
    "invalid_input",
)
ATTEMPT_ENDINGS = ("completed", "failed", "lease_expired", "released")

HASH = "~ '^[0-9a-f]{64}$'"


def _sha256_of(column: str) -> str:
    return f"encode(sha256(convert_to({column}, 'UTF8')), 'hex')"


def _in(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def _check(name: str, expression: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(expression, name=name)


def _id_and_tenant() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
    ]


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _tenant_keys(table: str) -> list[sa.Constraint]:
    return [
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        # Target of composite foreign keys; organization_id first (decision 0008).
        sa.UniqueConstraint("organization_id", "id", name=f"uq_{table}_organization_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["core.organizations.id"], name=f"fk_{table}_organization"
        ),
    ]


def _functions() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.refuse_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'rows of %.% are immutable', TG_TABLE_SCHEMA, TG_TABLE_NAME
                USING ERRCODE = 'check_violation';
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.jobs_before_insert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            base_hash text;
        BEGIN
            IF NEW.status <> 'queued' OR NEW.attempt <> 0
               OR num_nonnulls(NEW.outcome, NEW.lease_token, NEW.lease_expires_at,
                               NEW.heartbeat_at, NEW.worker_id, NEW.failure_code,
                               NEW.failure_message, NEW.executed_engine_version,
                               NEW.solver_name, NEW.solver_version, NEW.engine_fingerprint,
                               NEW.started_at, NEW.finished_at, NEW.cancelled_at) > 0 THEN
                RAISE EXCEPTION 'a job is created queued, with no lifecycle data'
                    USING ERRCODE = 'check_violation';
            END IF;
            -- The base snapshot is the grid exactly as submitted.
            SELECT content_hash INTO base_hash FROM {SCHEMA}.snapshots
             WHERE organization_id = NEW.organization_id AND id = NEW.base_snapshot_id;
            IF base_hash IS DISTINCT FROM NEW.source_topology_hash THEN
                RAISE EXCEPTION 'the base snapshot does not match the source topology hash'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """,  # noqa: S608  (constants only; no input reaches this SQL)
    )
    frozen = (
        "organization_id",
        "id",
        "source_grid_version",
        "source_topology_hash",
        "base_snapshot_id",
        "input_snapshot_id",
        "scenario_spec",
        "scenario_spec_hash",
        "configuration",
        "configuration_hash",
        "requested_engine_version",
        "idempotency_key",
        "request_fingerprint",
        "max_attempts",
        "created_at",
    )
    frozen_checks = "\n".join(
        f"""            IF NEW.{column} IS DISTINCT FROM OLD.{column} THEN
                RAISE EXCEPTION 'job column {column} cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;"""
        for column in frozen
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.jobs_before_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            unchanged {SCHEMA}.jobs;
        BEGIN
            -- A deleted grid or scenario sets its reference to NULL (foreign-key action).
            -- That is the one change allowed on any job, terminal or not.
            unchanged := NEW;
            unchanged.updated_at := OLD.updated_at;
            IF NEW.source_grid_id IS NULL THEN
                unchanged.source_grid_id := OLD.source_grid_id;
            END IF;
            IF NEW.scenario_id IS NULL THEN
                unchanged.scenario_id := OLD.scenario_id;
            END IF;
            IF unchanged IS NOT DISTINCT FROM OLD THEN
                RETURN NEW;
            END IF;
            IF NEW.source_grid_id IS DISTINCT FROM OLD.source_grid_id
               OR NEW.scenario_id IS DISTINCT FROM OLD.scenario_id THEN
                RAISE EXCEPTION 'a job''s grid or scenario reference can only be cleared'
                    USING ERRCODE = 'check_violation';
            END IF;
{frozen_checks}
            IF OLD.status IN ('completed', 'failed', 'cancelled') THEN
                RAISE EXCEPTION 'a % job never changes', OLD.status
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NOT EXISTS (SELECT 1 FROM {SCHEMA}.job_transitions
                            WHERE from_status = OLD.status AND to_status = NEW.status) THEN
                RAISE EXCEPTION 'a job cannot go from % to %', OLD.status, NEW.status
                    USING ERRCODE = 'check_violation';
            END IF;
            IF current_user = '{RUNTIME_ROLE}'
               AND NOT (OLD.status = 'queued' AND NEW.status = 'cancelled') THEN
                RAISE EXCEPTION 'the API may only cancel a queued job'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END
        $$
        """,  # noqa: S608  (constants only; no input reaches this SQL)
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.job_attempts_before_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            -- An attempt is recorded once when it starts and once when it ends.
            IF OLD.ended_at IS NOT NULL
               OR (NEW.organization_id, NEW.id, NEW.job_id, NEW.attempt, NEW.worker_id,
                   NEW.started_at)
                  IS DISTINCT FROM
                  (OLD.organization_id, OLD.id, OLD.job_id, OLD.attempt, OLD.worker_id,
                   OLD.started_at) THEN
                RAISE EXCEPTION 'an attempt can only be ended, once'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    for function in (
        "refuse_update()",
        "jobs_before_insert()",
        "jobs_before_update()",
        "job_attempts_before_update()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION {SCHEMA}.{function} FROM PUBLIC")


def _create_tables() -> None:
    op.create_table(
        "job_transitions",
        sa.Column("from_status", sa.Text(), nullable=False),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("from_status", "to_status", name="pk_job_transitions"),
        _check("from_status_known", f"from_status IN {_in(STATUSES)}"),
        _check("to_status_known", f"to_status IN {_in(STATUSES)}"),
        schema=SCHEMA,
    )
    op.bulk_insert(
        sa.table(
            "job_transitions",
            sa.column("from_status", sa.Text()),
            sa.column("to_status", sa.Text()),
            schema=SCHEMA,
        ),
        [{"from_status": a, "to_status": b} for a, b in TRANSITIONS],
    )

    op.create_table(
        "scenarios",
        *_id_and_tenant(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''"), nullable=False),
        # Canonical gridwise.scenario/1 text; its hash is checked by the database.
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("spec_hash", sa.Text(), nullable=False),
        _created_at(),
        *_tenant_keys("scenarios"),
        sa.UniqueConstraint("organization_id", "name", name="uq_scenarios_organization_name"),
        _check("name_not_blank", "length(btrim(name)) > 0"),
        _check("spec_is_json_object", "spec IS JSON OBJECT"),
        _check("spec_hash_matches", f"spec_hash = {_sha256_of('spec')}"),
        schema=SCHEMA,
    )

    op.create_table(
        "snapshots",
        *_id_and_tenant(),
        # Canonical gridwise.grid/2 text: exactly what the engine's grid_hash hashes.
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "document_schema",
            sa.Text(),
            server_default=sa.text("'gridwise.grid/2'"),
            nullable=False,
        ),
        sa.Column("element_count", sa.Integer(), nullable=False),
        _created_at(),
        *_tenant_keys("snapshots"),
        # One row per distinct content per tenant.
        sa.UniqueConstraint(
            "organization_id", "content_hash", name="uq_snapshots_organization_content_hash"
        ),
        _check("document_is_json_object", "document IS JSON OBJECT"),
        _check("content_hash_matches", f"content_hash = {_sha256_of('document')}"),
        _check("document_schema_known", "document_schema = 'gridwise.grid/2'"),
        _check("element_count_not_negative", "element_count >= 0"),
        schema=SCHEMA,
    )

    statuses_with_end = _in(("completed", "failed", "cancelled"))
    op.create_table(
        "jobs",
        *_id_and_tenant(),
        # --- what was submitted: never changes -------------------------------------------
        sa.Column("source_grid_id", sa.Uuid(), nullable=True),
        sa.Column("source_grid_version", sa.Integer(), nullable=False),
        sa.Column("source_topology_hash", sa.Text(), nullable=False),
        sa.Column("base_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("input_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=True),
        sa.Column("scenario_spec", sa.Text(), nullable=False),
        sa.Column("scenario_spec_hash", sa.Text(), nullable=False),
        sa.Column("configuration", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.Text(), nullable=False),
        sa.Column("requested_engine_version", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        # --- lifecycle ----------------------------------------------------------------
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        # --- what computed it (written once, at completion) ----------------------------
        sa.Column("executed_engine_version", sa.Text(), nullable=True),
        sa.Column("solver_name", sa.Text(), nullable=True),
        sa.Column("solver_version", sa.Text(), nullable=True),
        sa.Column("engine_fingerprint", sa.Text(), nullable=True),
        # --- time ------------------------------------------------------------------------
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_tenant_keys("jobs"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_jobs_organization_idempotency_key"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "base_snapshot_id"],
            ["sim.snapshots.organization_id", "sim.snapshots.id"],
            name="fk_jobs_base_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "input_snapshot_id"],
            ["sim.snapshots.organization_id", "sim.snapshots.id"],
            name="fk_jobs_input_snapshot",
        ),
        _check("status_known", f"status IN {_in(STATUSES)}"),
        _check("outcome_known", f"outcome IN {_in(OUTCOMES)}"),
        _check("failure_code_known", f"failure_code IN {_in(FAILURE_CODES)}"),
        _check("outcome_iff_completed", "(status = 'completed') = (outcome IS NOT NULL)"),
        _check("failure_iff_failed", "(status = 'failed') = (failure_code IS NOT NULL)"),
        _check("failure_message_with_code", "(failure_code IS NULL) = (failure_message IS NULL)"),
        _check("cancelled_at_iff_cancelled", "(status = 'cancelled') = (cancelled_at IS NOT NULL)"),
        _check(
            "lease_iff_running",
            "(status = 'running') = "
            "(lease_token IS NOT NULL AND lease_expires_at IS NOT NULL AND worker_id IS NOT NULL)",
        ),
        _check(
            "finished_at_iff_ended", f"(status IN {statuses_with_end}) = (finished_at IS NOT NULL)"
        ),
        _check(
            "started_unless_never_run",
            "status IN ('queued', 'cancelled') OR started_at IS NOT NULL",
        ),
        _check(
            "execution_record_complete",
            "num_nonnulls(executed_engine_version, solver_name, solver_version, "
            "engine_fingerprint) IN (0, 4) "
            "AND (status <> 'completed' OR engine_fingerprint IS NOT NULL)",
        ),
        _check("attempts_in_range", "attempt >= 0 AND attempt <= max_attempts"),
        _check("max_attempts_in_range", "max_attempts BETWEEN 1 AND 10"),
        _check("running_has_an_attempt", "status <> 'running' OR attempt >= 1"),
        _check("source_grid_version_positive", "source_grid_version >= 1"),
        _check(
            "times_ordered",
            "(started_at IS NULL OR started_at >= created_at) AND "
            "(finished_at IS NULL OR finished_at >= created_at)",
        ),
        _check("source_topology_hash_format", f"source_topology_hash {HASH}"),
        _check("request_fingerprint_format", f"request_fingerprint {HASH}"),
        _check("engine_fingerprint_format", f"engine_fingerprint {HASH}"),
        _check("idempotency_key_format", "idempotency_key ~ '^[!-~]{1,200}$'"),
        _check("scenario_spec_is_json_object", "scenario_spec IS JSON OBJECT"),
        _check("scenario_spec_hash_matches", f"scenario_spec_hash = {_sha256_of('scenario_spec')}"),
        _check("configuration_is_json_object", "configuration IS JSON OBJECT"),
        _check("configuration_hash_matches", f"configuration_hash = {_sha256_of('configuration')}"),
        schema=SCHEMA,
    )
    # A deleted grid or scenario leaves the job and clears only that reference. The column
    # list form (PostgreSQL 15+) keeps organization_id; Alembic cannot express it.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.jobs ADD CONSTRAINT fk_jobs_source_grid
            FOREIGN KEY (organization_id, source_grid_id)
            REFERENCES grid.grids (organization_id, id)
            ON DELETE SET NULL (source_grid_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.jobs ADD CONSTRAINT fk_jobs_scenario
            FOREIGN KEY (organization_id, scenario_id)
            REFERENCES {SCHEMA}.scenarios (organization_id, id)
            ON DELETE SET NULL (scenario_id)
        """
    )
    op.create_index(
        "ix_jobs_organization_status_created",
        "jobs",
        ["organization_id", "status", "created_at"],
        schema=SCHEMA,
    )
    for column in ("source_grid_id", "scenario_id", "base_snapshot_id", "input_snapshot_id"):
        op.create_index(f"ix_jobs_{column}", "jobs", [column], schema=SCHEMA)

    op.create_table(
        "job_attempts",
        *_id_and_tenant(),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.Text(), nullable=True),
        *_tenant_keys("job_attempts"),
        sa.UniqueConstraint(
            "organization_id", "job_id", "attempt", name="uq_job_attempts_organization_job_attempt"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["sim.jobs.organization_id", "sim.jobs.id"],
            name="fk_job_attempts_job",
            ondelete="CASCADE",
        ),
        _check("attempt_positive", "attempt >= 1"),
        _check("ended_by_known", f"ended_by IN {_in(ATTEMPT_ENDINGS)}"),
        _check("ended_together", "(ended_at IS NULL) = (ended_by IS NULL)"),
        _check("ended_after_started", "ended_at IS NULL OR ended_at >= started_at"),
        schema=SCHEMA,
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    # The tables first: the trigger functions refer to their row types.
    _create_tables()
    _functions()

    for table in ("scenarios", "snapshots"):
        op.execute(
            f"CREATE TRIGGER immutable BEFORE UPDATE ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.refuse_update()"
        )
    op.execute(
        f"CREATE TRIGGER immutable BEFORE UPDATE ON {SCHEMA}.job_transitions "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.refuse_update()"
    )
    op.execute(
        f"CREATE TRIGGER lifecycle_on_insert BEFORE INSERT ON {SCHEMA}.jobs "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.jobs_before_insert()"
    )
    op.execute(
        f"CREATE TRIGGER lifecycle BEFORE UPDATE ON {SCHEMA}.jobs "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.jobs_before_update()"
    )
    op.execute(
        f"CREATE TRIGGER end_once BEFORE UPDATE ON {SCHEMA}.job_attempts "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.job_attempts_before_update()"
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {SCHEMA}.{table}
            FOR ALL TO {RUNTIME_ROLE}
            USING (organization_id = core.current_organization_id())
            WITH CHECK (organization_id = core.current_organization_id())
            """
        )

    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT ON {SCHEMA}.job_transitions TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON {SCHEMA}.scenarios TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.snapshots TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {SCHEMA}.jobs TO {RUNTIME_ROLE}")
    # Cancelling is the API's only change to a job (the trigger checks the transition).
    op.execute(
        f"GRANT UPDATE (status, cancelled_at, finished_at) ON {SCHEMA}.jobs TO {RUNTIME_ROLE}"
    )
    op.execute(f"GRANT SELECT ON {SCHEMA}.job_attempts TO {RUNTIME_ROLE}")


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY tenant_isolation ON {SCHEMA}.{table}")
    op.drop_table("job_attempts", schema=SCHEMA)
    op.drop_table("jobs", schema=SCHEMA)
    op.drop_table("snapshots", schema=SCHEMA)
    op.drop_table("scenarios", schema=SCHEMA)
    op.drop_table("job_transitions", schema=SCHEMA)
    for function in (
        "job_attempts_before_update()",
        "jobs_before_update()",
        "jobs_before_insert()",
        "refuse_update()",
    ):
        op.execute(f"DROP FUNCTION {SCHEMA}.{function}")
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM {RUNTIME_ROLE}")
    op.execute(f"DROP SCHEMA {SCHEMA}")
