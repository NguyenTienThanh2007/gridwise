"""Reproduction: re-solving a finished job and recording whether the result held.

* ``sim.reproductions``   one row per reproduction attempt: the verdict, the hash and the
                          software that produced it. Append-only (never updated).
* ``sim.reproduction_candidates(limit)``  finished jobs not yet reproduced, across tenants
                          (ids only), for batch runs.
* ``sim.reproduction_input(job)``  what is needed to reproduce one job of the current tenant.
* ``sim.record_reproduction(...)``  records a reproduction. The verdict is decided here,
                          from the stored job and result, not by the caller.

All three functions are ``SECURITY DEFINER`` like the worker functions of 0004, executable
by ``gridwise_worker`` only. ``sim.claim_next_job`` is recreated to also return the engine
version a job was submitted with, so the worker can warn when it differs from its own.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "gridwise_app"
WORKER_ROLE = "gridwise_worker"
_DEFINER = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

VERDICTS = (
    "match",
    "mismatch",
    "differs_after_engine_change",
    "result_missing",
    "not_reproducible",
    "snapshot_corrupt",
    "reproduction_failed",
)
NEW_FUNCTIONS = (
    "sim.reproduction_candidates(integer)",
    "sim.reproduction_input(uuid)",
    "sim.record_reproduction(uuid, text, text, text, text, text, text, text)",
)


def _claim_function(*, with_engine_version: bool) -> str:
    """sim.claim_next_job as in 0004, optionally also returning the requested engine version."""
    extra_column = ", requested_engine_version text" if with_engine_version else ""
    extra_value = ", claimed.requested_engine_version" if with_engine_version else ""
    return f"""
        CREATE FUNCTION sim.claim_next_job(p_worker_id text, p_lease_seconds integer)
        RETURNS TABLE (job_id uuid, organization_id uuid, lease_token uuid, attempt integer,
                       input_document text, input_hash text, configuration text{extra_column})
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
            IF p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
                RAISE EXCEPTION 'lease must be between 5 and 3600 seconds'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;

            FOR expired IN
                SELECT j.* FROM sim.jobs j
                 WHERE j.status = 'running' AND j.lease_expires_at < clock_timestamp()
                 ORDER BY j.lease_expires_at
                 FOR UPDATE SKIP LOCKED
                 LIMIT 20
            LOOP
                UPDATE sim.job_attempts SET ended_at = clock_timestamp(), ended_by = 'lease_expired'
                 WHERE organization_id = expired.organization_id AND job_id = expired.id
                   AND attempt = expired.attempt AND ended_at IS NULL;
                IF expired.attempt < expired.max_attempts THEN
                    UPDATE sim.jobs SET status = 'queued', lease_token = NULL,
                           lease_expires_at = NULL, heartbeat_at = NULL, worker_id = NULL
                     WHERE id = expired.id;
                ELSE
                    UPDATE sim.jobs SET status = 'failed', failure_code = 'worker_lost',
                           failure_message = (SELECT message FROM sim.failure_catalogue
                                               WHERE code = 'worker_lost'),
                           lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
                           worker_id = NULL, finished_at = clock_timestamp()
                     WHERE id = expired.id;
                END IF;
            END LOOP;

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
                       s.document, s.content_hash, claimed.configuration{extra_value}
                  FROM sim.snapshots s
                 WHERE s.organization_id = claimed.organization_id
                   AND s.id = claimed.input_snapshot_id;
        END
        $$
        """


def _replace_claim(*, with_engine_version: bool) -> None:
    op.execute("DROP FUNCTION sim.claim_next_job(text, integer)")
    op.execute(_claim_function(with_engine_version=with_engine_version))
    op.execute("REVOKE ALL ON FUNCTION sim.claim_next_job(text, integer) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION sim.claim_next_job(text, integer) TO {WORKER_ROLE}")


def upgrade() -> None:
    verdicts = ", ".join(f"'{verdict}'" for verdict in VERDICTS)
    op.create_table(
        "reproductions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        # What the reproduction computed; NULL when nothing was solved.
        sa.Column("reproduced_outcome", sa.Text(), nullable=True),
        sa.Column("reproduced_result_hash", sa.Text(), nullable=True),
        # The software that reproduced it; NULL when nothing was solved.
        sa.Column("engine_version", sa.Text(), nullable=True),
        sa.Column("solver_name", sa.Text(), nullable=True),
        sa.Column("solver_version", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reproductions"),
        sa.ForeignKeyConstraint(
            ["organization_id", "job_id"],
            ["sim.jobs.organization_id", "sim.jobs.id"],
            name="fk_reproductions_job",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(f"verdict IN ({verdicts})", name="verdict_known"),
        sa.CheckConstraint(
            "reproduced_outcome IN ('converged', 'not_converged')", name="reproduced_outcome_known"
        ),
        sa.CheckConstraint(
            "reproduced_result_hash ~ '^[0-9a-f]{64}$'", name="reproduced_result_hash_format"
        ),
        sa.CheckConstraint(
            "num_nonnulls(engine_version, solver_name, solver_version) IN (0, 3)",
            name="software_complete",
        ),
        schema="sim",
    )
    op.create_index(
        "ix_reproductions_organization_job",
        "reproductions",
        ["organization_id", "job_id", "created_at"],
        schema="sim",
    )
    op.execute(
        "CREATE TRIGGER immutable BEFORE UPDATE ON sim.reproductions "
        "FOR EACH ROW EXECUTE FUNCTION sim.refuse_update()"
    )
    op.execute("ALTER TABLE sim.reproductions ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON sim.reproductions
        FOR ALL TO {RUNTIME_ROLE}
        USING (organization_id = core.current_organization_id())
        WITH CHECK (organization_id = core.current_organization_id())
        """
    )
    op.execute(f"GRANT SELECT ON sim.reproductions TO {RUNTIME_ROLE}")

    op.execute(
        f"""
        CREATE FUNCTION sim.reproduction_candidates(p_limit integer)
        RETURNS TABLE (job_id uuid, organization_id uuid)
        {_DEFINER} AS $$
        #variable_conflict use_column
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 1000 THEN
                RAISE EXCEPTION 'limit must be between 1 and 1000'
                    USING ERRCODE = 'invalid_parameter_value';
            END IF;
            RETURN QUERY
                SELECT j.id, j.organization_id FROM sim.jobs j
                 WHERE j.status = 'completed'
                   AND NOT EXISTS (SELECT 1 FROM sim.reproductions r
                                    WHERE r.organization_id = j.organization_id
                                      AND r.job_id = j.id)
                 ORDER BY j.finished_at, j.id
                 LIMIT p_limit;
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sim.reproduction_input(p_job_id uuid)
        RETURNS TABLE (job_id uuid, status text, outcome text, input_document text,
                       input_hash text, configuration text, stored_result_hash text,
                       executed_engine_version text, solver_name text, solver_version text)
        {_DEFINER} AS $$
        #variable_conflict use_column
        BEGIN
            RETURN QUERY
                SELECT j.id, j.status, j.outcome, s.document, s.content_hash, j.configuration,
                       r.result_hash, j.executed_engine_version, j.solver_name, j.solver_version
                  FROM sim.jobs j
                  JOIN sim.snapshots s
                    ON s.organization_id = j.organization_id AND s.id = j.input_snapshot_id
                  LEFT JOIN sim.results r
                    ON r.organization_id = j.organization_id AND r.job_id = j.id
                 WHERE j.id = p_job_id
                   AND j.organization_id = core.current_organization_id();
        END
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION sim.record_reproduction(
            p_job_id uuid, p_reproduced_outcome text, p_reproduced_result_hash text,
            p_engine_version text, p_solver_name text, p_solver_version text,
            p_worker_id text, p_problem text)
        RETURNS text
        {_DEFINER} AS $$
        DECLARE
            job sim.jobs;
            stored_hash text;
            verdict text;
            same boolean;
            solved boolean;
        BEGIN
            IF p_worker_id IS NULL OR p_worker_id !~ '^[A-Za-z0-9._:-]{{1,100}}$' THEN
                RAISE EXCEPTION 'invalid worker id' USING ERRCODE = 'invalid_parameter_value';
            END IF;
            IF p_problem IS NOT NULL
               AND p_problem NOT IN ('snapshot_corrupt', 'reproduction_failed') THEN
                RAISE EXCEPTION 'unknown problem' USING ERRCODE = 'invalid_parameter_value';
            END IF;
            SELECT j.* INTO job FROM sim.jobs j
             WHERE j.id = p_job_id AND j.organization_id = core.current_organization_id();
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;
            SELECT r.result_hash INTO stored_hash FROM sim.results r
             WHERE r.organization_id = job.organization_id AND r.job_id = job.id;

            -- The verdict follows from what is stored; the caller only reports what it got.
            IF job.status <> 'completed' THEN
                verdict := 'not_reproducible';
            ELSIF job.outcome = 'converged' AND stored_hash IS NULL THEN
                verdict := 'result_missing';
            ELSIF p_problem IS NOT NULL THEN
                verdict := p_problem;
            ELSIF p_reproduced_outcome IS NULL THEN
                RAISE EXCEPTION 'a reproduction that ran must report its outcome'
                    USING ERRCODE = 'invalid_parameter_value';
            ELSE
                same := p_reproduced_outcome = job.outcome
                        AND p_reproduced_result_hash IS NOT DISTINCT FROM stored_hash;
                IF same THEN
                    verdict := 'match';
                ELSIF (p_engine_version, p_solver_name, p_solver_version)
                      IS DISTINCT FROM
                      (job.executed_engine_version, job.solver_name, job.solver_version) THEN
                    verdict := 'differs_after_engine_change';
                ELSE
                    verdict := 'mismatch';
                END IF;
            END IF;

            solved := p_problem IS NULL
                      AND verdict NOT IN ('not_reproducible', 'result_missing');
            INSERT INTO sim.reproductions (organization_id, job_id, verdict, reproduced_outcome,
                                           reproduced_result_hash, engine_version, solver_name,
                                           solver_version, worker_id)
            VALUES (job.organization_id, job.id, verdict,
                    CASE WHEN solved THEN p_reproduced_outcome END,
                    CASE WHEN solved THEN p_reproduced_result_hash END,
                    p_engine_version, p_solver_name, p_solver_version, p_worker_id);
            RETURN verdict;
        END
        $$
        """
    )
    for function in NEW_FUNCTIONS:
        op.execute(f"REVOKE ALL ON FUNCTION {function} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {function} TO {WORKER_ROLE}")
    _replace_claim(with_engine_version=True)


def downgrade() -> None:
    _replace_claim(with_engine_version=False)
    for function in reversed(NEW_FUNCTIONS):
        op.execute(f"DROP FUNCTION {function}")
    op.execute("DROP POLICY tenant_isolation ON sim.reproductions")
    op.drop_table("reproductions", schema="sim")
