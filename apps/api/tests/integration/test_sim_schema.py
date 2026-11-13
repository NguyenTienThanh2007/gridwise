"""The sim schema's own rules: lifecycle, immutability, integrity, tenant isolation, grants.

The worker's moves are made in SQL as the owner role (the worker arrives in P1.3b); the
owner is not filtered by row-level security, so these tests show what the database enforces
for every role.
"""

import itertools
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.simulation.states import TRANSITIONS, JobStatus
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine.scenarios import demand_increase, scenario_document
from tests.support.simulations import (
    SIM_TABLES,
    claim,
    complete,
    counts,
    fail,
    job_row,
    requeue,
    service,
    stored_grid,
)

pytestmark = pytest.mark.integration

CHECK_VIOLATION = "23514"
INSUFFICIENT_PRIVILEGE = "42501"
FOREIGN_KEY_VIOLATION = "23503"
RLS_VIOLATION = "42501"


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _refused(engine: Engine, step: Callable[[Connection], object]) -> str | None:
    try:
        with engine.begin() as connection:
            step(connection)
    except DBAPIError as error:
        return _sqlstate(error)
    return None


@pytest.fixture
async def job_id(tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine) -> uuid.UUID:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    return (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job.id


def _sql(statement: str, **values: object) -> Callable[[Connection], object]:
    return lambda connection: connection.execute(text(statement), values)


# --- the transition table ---------------------------------------------------------------


def test_the_database_transition_table_is_the_domains(migrated: None, owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT from_status, to_status FROM sim.job_transitions")
        ).all()
    assert {(JobStatus(a), JobStatus(b)) for a, b in rows} == TRANSITIONS


def test_the_transition_table_cannot_be_changed(migrated: None, owner_engine: Engine) -> None:
    assert (
        _refused(owner_engine, _sql("UPDATE sim.job_transitions SET to_status = 'completed'"))
        == CHECK_VIOLATION
    )


# --- lifecycle --------------------------------------------------------------------------


def test_the_full_legal_lifecycle(job_id: uuid.UUID, owner_engine: Engine) -> None:
    with owner_engine.begin() as connection:
        claim(connection, job_id)
    assert job_row(owner_engine, job_id)["status"] == "running"
    with owner_engine.begin() as connection:  # heartbeat
        connection.execute(
            text(
                "UPDATE sim.jobs SET lease_expires_at = now() + interval '2 minutes', "
                "heartbeat_at = now() WHERE id = :id"
            ),
            {"id": job_id},
        )
    with owner_engine.begin() as connection:  # worker lost, back to the queue
        requeue(connection, job_id)
    with owner_engine.begin() as connection:
        claim(connection, job_id, worker="worker-2")
        complete(connection, job_id, outcome="not_converged")
    row = job_row(owner_engine, job_id)
    assert (row["status"], row["outcome"], row["attempt"]) == ("completed", "not_converged", 2)
    assert row["failure_code"] is None


@pytest.mark.parametrize(
    ("setup", "target"),
    [
        (
            [],
            "UPDATE sim.jobs SET status = 'completed', outcome = 'converged', finished_at = now()",
        ),
        (
            [],
            "UPDATE sim.jobs SET status = 'failed', failure_code = 'solver_failed', "
            "failure_message = 'x', finished_at = now()",
        ),
        (
            [claim],
            "UPDATE sim.jobs SET status = 'cancelled', cancelled_at = now(), "
            "finished_at = now(), lease_token = NULL, lease_expires_at = NULL, worker_id = NULL",
        ),
    ],
    ids=["queued-to-completed", "queued-to-failed", "running-to-cancelled"],
)
def test_illegal_moves_are_refused(
    job_id: uuid.UUID, owner_engine: Engine, setup: list[Callable[..., None]], target: str
) -> None:
    with owner_engine.begin() as connection:
        for step in setup:
            step(connection, job_id)
    before = job_row(owner_engine, job_id)
    assert _refused(owner_engine, _sql(target + " WHERE id = :id", id=job_id)) == CHECK_VIOLATION
    assert job_row(owner_engine, job_id) == before


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize(
    "change",
    [
        "status = 'queued'",
        "status = 'running'",
        "failure_message = 'rewritten'",
        "finished_at = now() + interval '1 hour'",
    ],
)
def test_a_terminal_job_never_changes(
    job_id: uuid.UUID, owner_engine: Engine, ending: str, change: str
) -> None:
    with owner_engine.begin() as connection:
        if ending == "cancelled":
            connection.execute(
                text(
                    "UPDATE sim.jobs SET status = 'cancelled', cancelled_at = now(), "
                    "finished_at = now() WHERE id = :id"
                ),
                {"id": job_id},
            )
        else:
            claim(connection, job_id)
            (complete if ending == "completed" else fail)(connection, job_id)
    before = job_row(owner_engine, job_id)
    state = _refused(owner_engine, _sql(f"UPDATE sim.jobs SET {change} WHERE id = :id", id=job_id))  # noqa: S608
    assert state == CHECK_VIOLATION
    assert job_row(owner_engine, job_id) == before


def test_an_update_that_changes_nothing_is_harmless(
    job_id: uuid.UUID, owner_engine: Engine
) -> None:
    """A no-op update passes the trigger (it is how cleared references are let through)
    and leaves the row exactly as it was, timestamps included."""
    with owner_engine.begin() as connection:
        claim(connection, job_id)
        complete(connection, job_id)
    before = job_row(owner_engine, job_id)
    assert (
        _refused(
            owner_engine, _sql("UPDATE sim.jobs SET outcome = outcome WHERE id = :id", id=job_id)
        )
        is None
    )
    assert job_row(owner_engine, job_id) == before


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("source_grid_version", "7"),
        ("source_topology_hash", "repeat('b', 64)"),
        ("input_snapshot_id", "uuidv7()"),
        ("configuration", "'{}'"),
        ("requested_engine_version", "'9.9.9'"),
        ("request_fingerprint", "repeat('c', 64)"),
        ("idempotency_key", "'late'"),
        ("max_attempts", "5"),
        ("created_at", "now() - interval '1 day'"),
        ("organization_id", "uuidv7()"),
        ("source_grid_id", "uuidv7()"),
    ],
)
def test_what_was_submitted_never_changes(
    job_id: uuid.UUID, owner_engine: Engine, column: str, value: str
) -> None:
    before = job_row(owner_engine, job_id)
    statement = f"UPDATE sim.jobs SET {column} = {value}, status = status WHERE id = :id"  # noqa: S608
    state = _refused(owner_engine, _sql(statement, id=job_id))
    assert state in (CHECK_VIOLATION, FOREIGN_KEY_VIOLATION)
    assert job_row(owner_engine, job_id) == before


def test_a_job_is_created_queued_and_empty(job_id: uuid.UUID, owner_engine: Engine) -> None:
    copy = (
        "INSERT INTO sim.jobs (organization_id, source_grid_version, source_topology_hash, "
        "base_snapshot_id, input_snapshot_id, scenario_spec, scenario_spec_hash, configuration, "
        "configuration_hash, requested_engine_version, request_fingerprint, status{extra_columns}) "
        "SELECT organization_id, source_grid_version, {hash}, base_snapshot_id, "
        "input_snapshot_id, scenario_spec, scenario_spec_hash, configuration, configuration_hash, "
        "requested_engine_version, request_fingerprint, {status}{extra_values} "
        "FROM sim.jobs WHERE id = :id"
    )
    running = copy.format(
        extra_columns="", hash="source_topology_hash", status="'running'", extra_values=""
    )
    assert _refused(owner_engine, _sql(running, id=job_id)) == CHECK_VIOLATION
    wrong_base = copy.format(
        extra_columns="", hash="repeat('d', 64)", status="'queued'", extra_values=""
    )
    assert _refused(owner_engine, _sql(wrong_base, id=job_id)) == CHECK_VIOLATION
    fine = copy.format(
        extra_columns="", hash="source_topology_hash", status="'queued'", extra_values=""
    )
    assert _refused(owner_engine, _sql(fine, id=job_id)) is None


@pytest.mark.parametrize(
    ("statement", "why"),
    [
        ("UPDATE sim.jobs SET status = 'running', attempt = 1, started_at = now()", "no lease"),
        ("UPDATE sim.jobs SET status = 'cancelled', finished_at = now()", "no cancelled_at"),
        ("UPDATE sim.jobs SET status = 'cancelled', cancelled_at = now()", "no finished_at"),
    ],
)
def test_lifecycle_columns_must_agree_with_the_status(
    job_id: uuid.UUID, owner_engine: Engine, statement: str, why: str
) -> None:
    assert _refused(owner_engine, _sql(statement + " WHERE id = :id", id=job_id)) == CHECK_VIOLATION


def test_failure_codes_come_from_the_catalogue(job_id: uuid.UUID, owner_engine: Engine) -> None:
    with owner_engine.begin() as connection:
        claim(connection, job_id)
    assert _refused(owner_engine, lambda c: fail(c, job_id, code="kaboom")) == CHECK_VIOLATION
    assert _refused(owner_engine, lambda c: fail(c, job_id, code="worker_lost")) is None


def test_a_completed_job_records_what_computed_it(job_id: uuid.UUID, owner_engine: Engine) -> None:
    with owner_engine.begin() as connection:
        claim(connection, job_id)
    incomplete = (
        "UPDATE sim.jobs SET status = 'completed', outcome = 'converged', lease_token = NULL, "
        "lease_expires_at = NULL, worker_id = NULL, finished_at = now() WHERE id = :id"
    )
    assert _refused(owner_engine, _sql(incomplete, id=job_id)) == CHECK_VIOLATION


# --- the runtime role ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE sim.jobs SET status = 'running'",
        "UPDATE sim.jobs SET status = 'failed', failure_code = 'solver_failed'",
        "UPDATE sim.jobs SET source_topology_hash = repeat('e', 64)",
        "UPDATE sim.jobs SET failure_message = 'x'",
        "DELETE FROM sim.jobs",
        "UPDATE sim.snapshots SET element_count = 0",
        "DELETE FROM sim.snapshots",
        "UPDATE sim.scenarios SET name = 'x'",
        "INSERT INTO sim.job_attempts (organization_id, job_id, attempt, worker_id) "
        "SELECT organization_id, id, 1, 'me' FROM sim.jobs",
        "UPDATE sim.job_attempts SET ended_by = 'completed'",
        "TRUNCATE sim.jobs",
        "INSERT INTO sim.job_transitions VALUES ('failed', 'queued')",
    ],
)
async def test_the_api_role_can_only_submit_and_cancel(
    job_id: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    owner_engine: Engine,
    statement: str,
) -> None:
    before = (job_row(owner_engine, job_id), counts(owner_engine))
    with pytest.raises(DBAPIError) as raised:
        async with tenant_transaction(app_async_engine, tenants["alpha"]) as session:
            await session.execute(text(statement))
    assert _sqlstate(raised.value) in (INSUFFICIENT_PRIVILEGE, CHECK_VIOLATION)
    assert (job_row(owner_engine, job_id), counts(owner_engine)) == before


# --- immutability and integrity -----------------------------------------------------------


@pytest.mark.parametrize("table", ["snapshots", "scenarios"])
async def test_snapshots_and_scenarios_never_change_even_for_the_owner(
    tenants: dict[str, uuid.UUID],
    app_async_engine: AsyncEngine,
    owner_engine: Engine,
    job_id: uuid.UUID,
    table: str,
) -> None:
    await service(app_async_engine).create_scenario(
        tenants["alpha"], name="S", description="", document=scenario_document(demand_increase())
    )
    column = {"snapshots": "element_count", "scenarios": "description"}[table]
    value = {"snapshots": "element_count", "scenarios": "description"}[table]
    statement = f"UPDATE sim.{table} SET {column} = {value}"  # noqa: S608
    assert _refused(owner_engine, _sql(statement)) == CHECK_VIOLATION


def test_a_snapshots_hash_is_checked_by_the_database_itself(
    job_id: uuid.UUID, owner_engine: Engine
) -> None:
    """Even with the immutability trigger switched off, damaged content cannot be stored."""

    def tamper(connection: Connection) -> None:
        connection.execute(text("ALTER TABLE sim.snapshots DISABLE TRIGGER immutable"))
        connection.execute(
            text("UPDATE sim.snapshots SET document = replace(document, '2.0', '2.5')")
        )

    assert _refused(owner_engine, tamper) == CHECK_VIOLATION
    copy_with_wrong_hash = (
        "INSERT INTO sim.snapshots (organization_id, document, content_hash, element_count) "
        "SELECT organization_id, document || ' ', content_hash, element_count FROM sim.snapshots"
    )
    assert _refused(owner_engine, _sql(copy_with_wrong_hash)) == CHECK_VIOLATION


def test_an_attempt_can_be_ended_only_once(job_id: uuid.UUID, owner_engine: Engine) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sim.job_attempts (organization_id, job_id, attempt, worker_id) "
                "SELECT organization_id, id, 1, 'w1' FROM sim.jobs WHERE id = :id"
            ),
            {"id": job_id},
        )
        connection.execute(
            text("UPDATE sim.job_attempts SET ended_at = now(), ended_by = 'lease_expired'")
        )
    assert (
        _refused(owner_engine, _sql("UPDATE sim.job_attempts SET ended_by = 'completed'"))
        == CHECK_VIOLATION
    )
    assert (
        _refused(owner_engine, _sql("UPDATE sim.job_attempts SET worker_id = 'w2'"))
        == CHECK_VIOLATION
    )


# --- tenant isolation ---------------------------------------------------------------------


async def test_no_sim_row_is_visible_without_tenant_context(
    job_id: uuid.UUID, app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    assert counts(owner_engine)["jobs"] == 1
    async with app_async_engine.connect() as connection:
        for table in SIM_TABLES:
            statement = text(f"SELECT count(*) FROM sim.{table}")  # noqa: S608
            count = (await connection.execute(statement)).scalar_one()
            assert count == 0, table


async def test_a_tenant_sees_only_its_own_sim_rows(
    tenants: dict[str, uuid.UUID], job_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, tenants["bravo"]) as session:
        for table in SIM_TABLES:
            count = (await session.execute(text(f"SELECT count(*) FROM sim.{table}"))).scalar_one()  # noqa: S608
            assert count == 0, table
        cancelled = await session.execute(
            text(
                "UPDATE sim.jobs SET status = 'cancelled', cancelled_at = now(), "
                "finished_at = now() WHERE id = :id"
            ),
            {"id": job_id},
        )
        assert cancelled.rowcount == 0
    async with tenant_transaction(app_async_engine, tenants["alpha"]) as session:
        assert (await session.execute(text("SELECT count(*) FROM sim.jobs"))).scalar_one() == 1


async def test_a_tenant_cannot_write_sim_rows_for_another(
    tenants: dict[str, uuid.UUID], job_id: uuid.UUID, app_async_engine: AsyncEngine
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with tenant_transaction(app_async_engine, tenants["bravo"]) as session:
            await session.execute(
                text(
                    "INSERT INTO sim.scenarios (organization_id, name, spec, spec_hash) "
                    "VALUES (:org, 'planted', '{}', encode(sha256('{}'::bytea), 'hex'))"
                ),
                {"org": tenants["alpha"]},
            )
    assert _sqlstate(raised.value) == RLS_VIOLATION


async def test_snapshot_deduplication_cannot_reveal_another_tenants_content(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    """Both tenants submit the same grid: each gets a snapshot row of its own."""
    alpha_grid = await stored_grid(app_async_engine, tenants["alpha"])
    bravo_grid = await stored_grid(app_async_engine, tenants["bravo"])
    alpha_job = (await service(app_async_engine).submit(tenants["alpha"], alpha_grid)).job
    bravo_job = (await service(app_async_engine).submit(tenants["bravo"], bravo_grid)).job
    assert alpha_job.source_topology_hash == bravo_job.source_topology_hash
    assert alpha_job.input_snapshot_id != bravo_job.input_snapshot_id
    assert counts(owner_engine)["snapshots"] == 2


def test_every_sim_table_has_row_level_security(migrated: None, admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'sim' AND c.relkind = 'r'"
            )
        ).all()
        policies = connection.execute(
            text(
                "SELECT tablename, cmd, roles::text, qual, with_check FROM pg_policies "
                "WHERE schemaname = 'sim' ORDER BY tablename"
            )
        ).all()
    enabled = {row.relname: row.relrowsecurity for row in rows}
    assert enabled == {**dict.fromkeys(SIM_TABLES, True), "job_transitions": False}
    condition = "(organization_id = core.current_organization_id())"
    assert [tuple(row) for row in policies] == [
        (table, "ALL", "{gridwise_app}", condition, condition) for table in sorted(SIM_TABLES)
    ]


def test_every_transition_pair_is_enforced_by_the_database(
    tenants: dict[str, uuid.UUID], migrated: None, owner_engine: Engine
) -> None:
    """The trigger refuses exactly the pairs the domain refuses (status only; the other
    columns are set to whatever the target status requires)."""
    legal = {(a.value, b.value) for a, b in TRANSITIONS}
    with owner_engine.connect() as connection:
        refused = {
            (a, b)
            for a, b in itertools.product([s.value for s in JobStatus], repeat=2)
            if not connection.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM sim.job_transitions "
                    "WHERE from_status = :a AND to_status = :b)"
                ),
                {"a": a, "b": b},
            ).scalar_one()
        }
    assert refused == set(itertools.product([s.value for s in JobStatus], repeat=2)) - legal
