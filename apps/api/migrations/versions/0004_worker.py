"""Worker: lifecycle functions, results, the failure catalogue and the worker's grants.

The simulation worker (role ``gridwise_worker``) has no privilege on any table. It reaches
jobs only through five functions, which run as their owner and check everything a worker
could get wrong (decision 0011):

* ``sim.claim_next_job``    reap expired leases, then take the oldest queued job;
* ``sim.heartbeat_job``     extend the lease;
* ``sim.complete_job``      store the result and the terminal status in one transaction;
* ``sim.fail_job``          record a failure, with the message from the catalogue;
* ``sim.release_job``       give the job back (shutdown, lost child process).

Every call except the claim requires the job's lease token, an unexpired lease (database
clock), and the transaction's tenant context set to the job's organisation. A worker whose
lease was taken over gets ``false`` and changes nothing.

The functions are ``SECURITY DEFINER`` with a fixed ``search_path`` and fully qualified
names, and only ``gridwise_worker`` may execute them.

Also: ``sim.results`` (one immutable result per converged job, written only by
``complete_job``), ``sim.failure_catalogue`` (the only failure messages there are), a check
that a queued job has an attempt left, and indexes for claiming across tenants.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "gridwise_app"
WORKER_ROLE = "gridwise_worker"

#: Must equal gridwise_api.simulation.failures.FAILURE_MESSAGES (a test compares them).
FAILURE_CATALOGUE = (
    ("solver_failed", "The power flow solver stopped with an error."),
    (
        "inconsistent_solution",
        "The solver returned a solution that failed the engine's consistency checks. "
        "It was not stored.",
    ),
    ("execution_timeout", "The computation did not finish within the time limit."),
    ("worker_lost", "The worker running this job stopped responding, on every attempt."),
    ("snapshot_corrupt", "The stored input did not match its hash and was not used."),
    ("invalid_input", "The stored input is not a valid grid for this engine version."),
)

_DEFINER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

FUNCTIONS = (
    "sim.claim_next_job(text, integer)",
    "sim.heartbeat_job(uuid, uuid, integer)",
    "sim.complete_job(uuid, uuid, text, text, text, text, text, text, text)",
    "sim.fail_job(uuid, uuid, text)",
    "sim.release_job(uuid, uuid)",
)


def _require_role(name: str) -> None:
    exists = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": name})
        .scalar()
    )
    if not exists:
        raise RuntimeError(
            f"Role {name!r} does not exist. New database volumes get it from "
            "infrastructure/postgres/init/010-gridwise-roles.sh; for an existing volume run "
            "`make db-worker-role`."
        )


def _tables() -> None:
    op.create_table(
        "failure_catalogue",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("code", name="pk_failure_catalogue"),
        schema="sim",
    )
    op.bulk_insert(
        sa.table(
            "failure_catalogue",
            sa.column("code", sa.Text()),
            sa.column("message", sa.Text()),
            schema="sim",
        ),
        [{"code": code, "message": message} for code, message in FAILURE_CATALOGUE],
    )
    op.execute(
        "CREATE TRIGGER immutable BEFORE UPDATE ON sim.failure_catalogue "
        "FOR EACH ROW EXECUTE FUNCTION sim.refuse_update()"
    )
    op.create_unique_constraint(
        "uq_failure_catalogue_code_message", "failure_catalogue", ["code", "message"], schema="sim"
    )
    # A failed job's code and message must be a catalogue entry, word for word.
    op.create_foreign_key(
        "fk_jobs_failure",
        "jobs",
        "failure_catalogue",
        ["failure_code", "failure_message"],
        ["code", "message"],
        source_schema="sim",
        referent_schema="sim",
    )

    op.create_table(
        "results",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        # Canonical text of the engine's PowerFlowResult, exactly as computed.
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.Text(), nullable=False),
        # The engine's result_hash (rounded values), for reproduction checks.
        sa.Column("result_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_results"),
        sa.UniqueConstraint("organization_id", "job_id", name="uq_results_organization_job"),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["sim.jobs.organization_id", "sim.jobs.id"],
            name="fk_results_job",
        ),
        sa.CheckConstraint("document IS JSON OBJECT", name="document_is_json_object"),
        sa.CheckConstraint(
            "document_hash = encode(sha256(convert_to(document, 'UTF8')), 'hex')",
            name="document_hash_matches",
        ),
        sa.CheckConstraint("result_hash ~ '^[0-9a-f]{64}$'", name="result_hash_format"),
        schema="sim",
    )
    op.execute(
        "CREATE TRIGGER immutable BEFORE UPDATE ON sim.results "
        "FOR EACH ROW EXECUTE FUNCTION sim.refuse_update()"
    )
    op.execute("ALTER TABLE sim.results ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON sim.results
        FOR ALL TO {RUNTIME_ROLE}
        USING (organization_id = core.current_organization_id())
        WITH CHECK (organization_id = core.current_organization_id())
        """
    )

    # A queued job always has an attempt left; otherwise the claim could never take it.
    op.create_check_constraint(
        op.f("ck_jobs_queued_has_an_attempt_left"),
        "jobs",
        "status <> 'queued' OR attempt < max_attempts",
        schema="sim",
    )
    # Claiming and reaping look across tenants.
    op.create_index(
        "ix_jobs_queued",
        "jobs",
        ["created_at", "id"],
        schema="sim",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_jobs_running_lease",
        "jobs",
        ["lease_expires_at"],
        schema="sim",
        postgresql_where=sa.text("status = 'running'"),
    )


_CHECK_LEASE_ARGUMENTS = """
            IF p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
                RAISE EXCEPTION 'lease must be between 5 and 3600 seconds'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;"""

# The job, locked, if the caller holds its live lease under the job's tenant context.
_HELD_JOB = """
            SELECT j.* INTO held FROM sim.jobs j
             WHERE j.id = p_job_id
               AND j.organization_id = core.current_organization_id()
               AND j.status = 'running'
               AND j.lease_token = p_lease_token
               AND j.lease_expires_at >= clock_timestamp()
             FOR UPDATE;"""

_END_ATTEMPT = """
            UPDATE sim.job_attempts SET ended_at = clock_timestamp(), ended_by = {ending}
             WHERE organization_id = {job}.organization_id AND job_id = {job}.id
               AND attempt = {job}.attempt AND ended_at IS NULL;"""

_GIVE_BACK = """
            IF {job}.attempt < {job}.max_attempts THEN
                UPDATE sim.jobs SET status = 'queued', lease_token = NULL,
                       lease_expires_at = NULL, heartbeat_at = NULL, worker_id = NULL
                 WHERE id = {job}.id;
            ELSE
                UPDATE sim.jobs SET status = 'failed', failure_code = 'worker_lost',
                       failure_message = (SELECT message FROM sim.failure_catalogue
                                           WHERE code = 'worker_lost'),
                       lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                       worker_id = NULL, finished_at = clock_timestamp()
                 WHERE id = {job}.id;
            END IF;"""


def _functions() -> None:
    op.execute(
        f"""
        CREATE FUNCTION sim.claim_next_job(p_worker_id text, p_lease_seconds integer)
        RETURNS TABLE (job_id uuid, organization_id uuid, lease_token uuid, attempt integer,
                       input_document text, input_hash text, configuration text)
        {_DEFINER} AS $$
        #variable_conflict use_column
        DECLARE
            expired sim.jobs;
            claimed sim.jobs;
            token uuid := gen_random_uuid();
        BEGIN
            IF p_worker_id IS NULL OR p_worker_id !~ '^[A-Za-z0-9._:-]{{1,100}}$' THEN
                RAISE EXCEPTION 'invalid worker id' USING ERRCODE = 'invalid_parameter_value';
            END IF;
{_CHECK_LEASE_ARGUMENTS}

            -- 1. Leases that expired: their worker was lost. Requeue or fail, and record it.
            FOR expired IN
                SELECT j.* FROM sim.jobs j
                 WHERE j.status = 'running' AND j.lease_expires_at < clock_timestamp()
                 ORDER BY j.lease_expires_at
                 FOR UPDATE SKIP LOCKED
                 LIMIT 20
            LOOP
{_END_ATTEMPT.format(ending="'lease_expired'", job="expired")}
{_GIVE_BACK.format(job="expired")}
            END LOOP;

            -- 2. The oldest queued job nobody else is taking right now.
            SELECT j.* INTO claimed FROM sim.jobs j
             WHERE j.status = 'queued'
             ORDER BY j.created_at, j.id
             FOR UPDATE SKIP LOCKED
             LIMIT 1;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            UPDATE sim.jobs SET status = 'running', attempt = sim.jobs.attempt + 1,
                   lease_token = token,
                   lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
                   heartbeat_at = clock_timestamp(), worker_id = p_worker_id,
                   started_at = coalesce(sim.jobs.started_at, clock_timestamp())
             WHERE sim.jobs.id = claimed.id
             RETURNING * INTO claimed;
            INSERT INTO sim.job_attempts (organization_id, job_id, attempt, worker_id, started_at)
            VALUES (claimed.organization_id, claimed.id, claimed.attempt, p_worker_id,
                    clock_timestamp());

            RETURN QUERY
                SELECT claimed.id, claimed.organization_id, token, claimed.attempt,
                       s.document, s.content_hash, claimed.configuration
                  FROM sim.snapshots s
                 WHERE s.organization_id = claimed.organization_id
                   AND s.id = claimed.input_snapshot_id;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sim.heartbeat_job(p_job_id uuid, p_lease_token uuid,
                                          p_lease_seconds integer)
        RETURNS boolean
        {_DEFINER} AS $$
        DECLARE
            held sim.jobs;
        BEGIN
{_CHECK_LEASE_ARGUMENTS}
{_HELD_JOB}
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            UPDATE sim.jobs
               SET lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
                   heartbeat_at = clock_timestamp()
             WHERE id = held.id;
            RETURN true;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sim.complete_job(
            p_job_id uuid, p_lease_token uuid, p_outcome text, p_engine_version text,
            p_solver_name text, p_solver_version text, p_engine_fingerprint text,
            p_result_document text, p_result_hash text)
        RETURNS boolean
        {_DEFINER} AS $$
        DECLARE
            held sim.jobs;
        BEGIN
{_HELD_JOB}
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            IF p_outcome = 'converged' THEN
                IF p_result_document IS NULL OR p_result_hash IS NULL THEN
                    RAISE EXCEPTION 'a converged job needs its result'
                        USING ERRCODE = 'invalid_parameter_value';
                END IF;
                INSERT INTO sim.results (organization_id, job_id, document, document_hash,
                                         result_hash)
                VALUES (held.organization_id, held.id, p_result_document,
                        encode(sha256(convert_to(p_result_document, 'UTF8')), 'hex'),
                        p_result_hash);
            ELSIF p_outcome = 'not_converged' THEN
                IF p_result_document IS NOT NULL OR p_result_hash IS NOT NULL THEN
                    RAISE EXCEPTION 'a job that did not converge has no result'
                        USING ERRCODE = 'invalid_parameter_value';
                END IF;
            ELSE
                RAISE EXCEPTION 'unknown outcome' USING ERRCODE = 'invalid_parameter_value';
            END IF;
            UPDATE sim.jobs SET status = 'completed', outcome = p_outcome,
                   lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                   worker_id = NULL, finished_at = clock_timestamp(),
                   executed_engine_version = p_engine_version, solver_name = p_solver_name,
                   solver_version = p_solver_version, engine_fingerprint = p_engine_fingerprint
             WHERE id = held.id;
{_END_ATTEMPT.format(ending="'completed'", job="held")}
            RETURN true;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sim.fail_job(p_job_id uuid, p_lease_token uuid, p_failure_code text)
        RETURNS boolean
        {_DEFINER} AS $$
        DECLARE
            held sim.jobs;
            catalogued text;
        BEGIN
            -- worker_lost is decided by the database (lease expiry), never reported.
            SELECT message INTO catalogued FROM sim.failure_catalogue
             WHERE code = p_failure_code AND code <> 'worker_lost';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'unknown failure code' USING ERRCODE = 'invalid_parameter_value';
            END IF;
{_HELD_JOB}
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            UPDATE sim.jobs SET status = 'failed', failure_code = p_failure_code,
                   failure_message = catalogued, lease_token = NULL, lease_expires_at = NULL,
                   heartbeat_at = NULL, worker_id = NULL, finished_at = clock_timestamp()
             WHERE id = held.id;
{_END_ATTEMPT.format(ending="'failed'", job="held")}
            RETURN true;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sim.release_job(p_job_id uuid, p_lease_token uuid)
        RETURNS boolean
        {_DEFINER} AS $$
        DECLARE
            held sim.jobs;
        BEGIN
{_HELD_JOB}
            IF NOT FOUND THEN
                RETURN false;
            END IF;
{_END_ATTEMPT.format(ending="'released'", job="held")}
{_GIVE_BACK.format(job="held")}
            RETURN true;
        END
        $$
        """
    )
    for function in FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")


def upgrade() -> None:
    _require_role(WORKER_ROLE)
    _tables()
    _functions()
    op.execute(f"GRANT USAGE ON SCHEMA sim TO {WORKER_ROLE}")
    # The worker refuses to start against a schema revision it was not built for.
    op.execute(f"GRANT SELECT ON public.alembic_version TO {WORKER_ROLE}")
    op.execute(f"GRANT SELECT ON sim.results TO {RUNTIME_ROLE}")


def downgrade() -> None:
    for function in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
    op.execute(f"REVOKE SELECT ON public.alembic_version FROM {WORKER_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA sim FROM {WORKER_ROLE}")
    op.drop_index("ix_jobs_running_lease", table_name="jobs", schema="sim")
    op.drop_index("ix_jobs_queued", table_name="jobs", schema="sim")
    op.drop_constraint(
        op.f("ck_jobs_queued_has_an_attempt_left"), "jobs", schema="sim", type_="check"
    )
    op.execute("DROP POLICY tenant_isolation ON sim.results")
    op.drop_table("results", schema="sim")
    op.drop_constraint("fk_jobs_failure", "jobs", schema="sim", type_="foreignkey")
    op.drop_table("failure_catalogue", schema="sim")
