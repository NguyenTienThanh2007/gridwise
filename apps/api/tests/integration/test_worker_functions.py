"""The worker's database functions (migration 0004), called as the worker role.

The worker role has no table privileges. These tests show that the functions alone keep
leases exclusive, make stale workers harmless, write results and terminal states together,
keep failure messages to the catalogue, and respect tenant boundaries.
"""

import threading
import uuid
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.simulation.failures import FAILURE_MESSAGES
from gridwise_worker.database import Completion, WorkerDatabase
from tests.support.simulations import job_row, service, stored_grid

pytestmark = pytest.mark.integration

INSUFFICIENT_PRIVILEGE = "42501"
INVALID_PARAMETER = "22023"
CHECK_VIOLATION = "23514"


def _db(engine: Engine, worker_id: str = "worker-a", lease_seconds: int = 60) -> WorkerDatabase:
    return WorkerDatabase(engine, worker_id=worker_id, lease_seconds=lease_seconds)


def _converged(**changes: Any) -> Completion:
    values: dict[str, Any] = {
        "outcome": "converged",
        "engine_version": "0.3.0",
        "solver_name": "pandapower",
        "solver_version": "3.5.6",
        "engine_fingerprint": "f" * 64,
        "result_document": '{"schema":"test","value":1.0}',
        "result_hash": "e" * 64,
    }
    return Completion(**{**values, **changes})


def _expire(owner: Engine, job_id: uuid.UUID) -> None:
    """Make a lease run out now, as if its worker had stopped responding."""
    with owner.begin() as connection:
        connection.execute(
            text(
                "UPDATE sim.jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": job_id},
        )


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


@pytest.fixture
async def queued(tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine) -> uuid.UUID:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    return (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job.id


def _attempts(owner: Engine, job_id: uuid.UUID) -> list[tuple[int, str, str | None]]:
    with owner.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT attempt, worker_id, ended_by FROM sim.job_attempts "
                    "WHERE job_id = :id ORDER BY attempt"
                ),
                {"id": job_id},
            )
        ]


# --- claiming -----------------------------------------------------------------------------


def test_a_claim_takes_the_job_with_a_fresh_lease(
    queued: uuid.UUID, tenants: dict[str, uuid.UUID], worker_engine: Engine, owner_engine: Engine
) -> None:
    lease = _db(worker_engine).claim()
    assert lease is not None
    assert (lease.job_id, lease.organization_id, lease.attempt) == (queued, tenants["alpha"], 1)
    assert lease.token.version == 4  # random, not time-ordered
    row = job_row(owner_engine, queued)
    assert (row["status"], row["worker_id"], row["lease_token"]) == (
        "running",
        "worker-a",
        lease.token,
    )
    assert row["started_at"] is not None
    assert _attempts(owner_engine, queued) == [(1, "worker-a", None)]
    assert '"schema":"gridwise.grid/2"' in lease.input_document
    assert '"algorithm":"newton_raphson"' in lease.configuration


def test_nothing_to_claim(migrated: None, worker_engine: Engine) -> None:
    assert _db(worker_engine).claim() is None


async def test_jobs_are_claimed_oldest_first_across_tenants(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine, worker_engine: Engine
) -> None:
    alpha_grid = await stored_grid(app_async_engine, tenants["alpha"])
    bravo_grid = await stored_grid(app_async_engine, tenants["bravo"])
    order = [
        (await service(app_async_engine).submit(tenants["alpha"], alpha_grid)).job.id,
        (await service(app_async_engine).submit(tenants["bravo"], bravo_grid)).job.id,
        (await service(app_async_engine).submit(tenants["alpha"], alpha_grid)).job.id,
    ]
    claimed = []
    while (lease := _db(worker_engine).claim()) is not None:
        claimed.append((lease.job_id, lease.organization_id))
    assert [job for job, _ in claimed] == order
    assert [org for _, org in claimed] == [tenants["alpha"], tenants["bravo"], tenants["alpha"]]


async def test_concurrent_workers_never_share_a_job(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine, worker_engine: Engine
) -> None:
    grid = await stored_grid(app_async_engine, tenants["alpha"])
    jobs = {
        (await service(app_async_engine).submit(tenants["alpha"], grid)).job.id for _ in range(30)
    }
    claims: list[tuple[str, uuid.UUID, uuid.UUID]] = []
    lock = threading.Lock()
    start = threading.Barrier(6)

    def work(name: str) -> None:
        database = _db(worker_engine, worker_id=name)
        start.wait()
        while (lease := database.claim()) is not None:
            with lock:
                claims.append((name, lease.job_id, lease.token))

    threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    claimed_jobs = [job for _, job, _ in claims]
    assert sorted(map(str, claimed_jobs)) == sorted(map(str, jobs))  # each exactly once
    assert len({token for _, _, token in claims}) == 30
    assert len({name for name, _, _ in claims}) > 1  # really concurrent


# --- the worker role ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT count(*) FROM sim.jobs",
        "SELECT count(*) FROM sim.snapshots",
        "SELECT count(*) FROM sim.results",
        "SELECT count(*) FROM grid.grids",
        "UPDATE sim.jobs SET status = 'queued'",
        "INSERT INTO sim.results (organization_id, job_id, document, document_hash, result_hash) "
        "VALUES (uuidv7(), uuidv7(), '{}', '', '')",
        "DELETE FROM sim.job_attempts",
        "SELECT count(*) FROM core.organizations",
    ],
)
def test_the_worker_role_has_no_table_access(
    queued: uuid.UUID, worker_engine: Engine, statement: str
) -> None:
    with pytest.raises(DBAPIError) as raised, worker_engine.begin() as connection:
        connection.execute(text(statement))
    assert _sqlstate(raised.value) == INSUFFICIENT_PRIVILEGE


def test_only_the_worker_role_may_call_the_worker_functions(
    queued: uuid.UUID, app_engine: Engine, owner_engine: Engine
) -> None:
    with pytest.raises(DBAPIError) as raised, app_engine.begin() as connection:
        connection.execute(text("SELECT * FROM sim.claim_next_job('api', 60)"))
    assert _sqlstate(raised.value) == INSUFFICIENT_PRIVILEGE
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT p.proname, p.prosecdef, p.proconfig::text, pg_get_userbyid(p.proowner), "
                "has_function_privilege('gridwise_worker', p.oid, 'EXECUTE'), "
                "has_function_privilege('gridwise_app', p.oid, 'EXECUTE'), "
                "EXISTS (SELECT 1 FROM aclexplode(p.proacl) acl WHERE acl.grantee = 0) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'sim' AND p.proname LIKE '%_job' ORDER BY 1"
            )
        ).all()
    assert [row[0] for row in rows] == [
        "claim_next_job",
        "complete_job",
        "fail_job",
        "heartbeat_job",
        "release_job",
    ]
    for name, definer, config, owner, worker_may, app_may, public_may in rows:
        assert definer is True, name
        assert config == '{"search_path=pg_catalog, pg_temp"}', name
        assert owner == "gridwise_owner", name
        assert (worker_may, app_may, public_may) == (True, False, False), name


@pytest.mark.parametrize(
    ("worker_id", "lease_seconds"),
    [("has space", 60), ("", 60), ("x" * 101, 60), ("ok", 4), ("ok", 3601)],
)
def test_claim_arguments_are_checked(
    migrated: None, worker_engine: Engine, worker_id: str, lease_seconds: int
) -> None:
    with pytest.raises(DBAPIError) as raised:
        _db(worker_engine, worker_id=worker_id, lease_seconds=lease_seconds).claim()
    assert _sqlstate(raised.value) == INVALID_PARAMETER


# --- leases -------------------------------------------------------------------------------


def test_a_heartbeat_extends_only_a_live_lease_held_by_the_caller(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    before = job_row(owner_engine, queued)["lease_expires_at"]
    assert database.heartbeat(lease) is True
    assert job_row(owner_engine, queued)["lease_expires_at"] > before

    assert database.heartbeat(replace(lease, token=uuid.uuid4())) is False
    _expire(owner_engine, queued)
    assert database.heartbeat(lease) is False  # an expired lease is not renewed


def test_calls_about_a_job_need_its_tenant_context(
    queued: uuid.UUID, tenants: dict[str, uuid.UUID], worker_engine: Engine, owner_engine: Engine
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    elsewhere = replace(lease, organization_id=tenants["bravo"])
    assert database.heartbeat(elsewhere) is False
    assert database.complete(elsewhere, _converged()) is False
    assert database.fail(elsewhere, "solver_failed") is False
    assert database.release(elsewhere) is False
    assert job_row(owner_engine, queued)["status"] == "running"
    assert database.complete(lease, _converged()) is True


def test_an_expired_lease_is_requeued_by_the_next_claim(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    first = _db(worker_engine, "worker-a").claim()
    assert first is not None
    _expire(owner_engine, queued)
    second = _db(worker_engine, "worker-b").claim()
    assert second is not None
    assert (second.job_id, second.attempt) == (queued, 2)
    assert second.token != first.token
    assert _attempts(owner_engine, queued) == [
        (1, "worker-a", "lease_expired"),
        (2, "worker-b", None),
    ]


def test_a_stale_worker_cannot_touch_a_job_that_was_taken_over(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    stale = _db(worker_engine, "worker-a")
    lease_a = stale.claim()
    assert lease_a is not None
    _expire(owner_engine, queued)
    fresh = _db(worker_engine, "worker-b")
    lease_b = fresh.claim()
    assert lease_b is not None

    assert stale.complete(lease_a, _converged(result_hash="a" * 64)) is False
    assert stale.fail(lease_a, "solver_failed") is False
    assert stale.release(lease_a) is False
    assert stale.heartbeat(lease_a) is False
    assert job_row(owner_engine, queued)["worker_id"] == "worker-b"

    assert fresh.complete(lease_b, _converged(result_hash="b" * 64)) is True
    with owner_engine.connect() as connection:
        results = connection.execute(text("SELECT result_hash FROM sim.results")).scalars().all()
    assert results == ["b" * 64]


def test_after_the_last_attempt_a_lost_worker_fails_the_job(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    for attempt in (1, 2, 3):
        lease = _db(worker_engine, f"w{attempt}").claim()
        assert lease is not None
        assert lease.attempt == attempt
        _expire(owner_engine, queued)
    assert _db(worker_engine, "w4").claim() is None  # reaped, nothing left to claim
    row = job_row(owner_engine, queued)
    assert (row["status"], row["failure_code"]) == ("failed", "worker_lost")
    assert row["failure_message"] == FAILURE_MESSAGES["worker_lost"]  # type: ignore[index]
    assert [ending for _, _, ending in _attempts(owner_engine, queued)] == ["lease_expired"] * 3


def test_a_queued_job_always_has_an_attempt_left(queued: uuid.UUID, owner_engine: Engine) -> None:
    with pytest.raises(DBAPIError) as raised, owner_engine.begin() as connection:
        connection.execute(
            text("UPDATE sim.jobs SET max_attempts = 1, attempt = 1 WHERE id = :id"), {"id": queued}
        )
    assert _sqlstate(raised.value) == CHECK_VIOLATION


# --- outcomes -----------------------------------------------------------------------------


def test_completion_stores_the_result_and_the_terminal_state_together(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    assert database.complete(lease, _converged()) is True
    row = job_row(owner_engine, queued)
    assert (row["status"], row["outcome"], row["lease_token"]) == ("completed", "converged", None)
    assert (row["solver_name"], row["solver_version"], row["engine_fingerprint"]) == (
        "pandapower",
        "3.5.6",
        "f" * 64,
    )
    with owner_engine.connect() as connection:
        result = connection.execute(text("SELECT * FROM sim.results")).mappings().one()
    assert result["job_id"] == queued
    assert result["document"] == '{"schema":"test","value":1.0}'
    assert _attempts(owner_engine, queued) == [(1, "worker-a", "completed")]
    assert database.complete(lease, _converged()) is False  # no second completion


def test_a_completion_the_database_refuses_leaves_nothing_behind(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    with pytest.raises(DBAPIError):
        database.complete(lease, _converged(result_hash="not-a-hash"))
    assert job_row(owner_engine, queued)["status"] == "running"
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sim.results")).scalar_one() == 0


def test_non_convergence_completes_without_a_result(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    with pytest.raises(DBAPIError) as raised:
        database.complete(lease, _converged(outcome="not_converged"))  # carries values
    assert _sqlstate(raised.value) == INVALID_PARAMETER
    empty = _converged(outcome="not_converged", result_document=None, result_hash=None)
    assert database.complete(lease, empty) is True
    assert job_row(owner_engine, queued)["outcome"] == "not_converged"
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sim.results")).scalar_one() == 0


@pytest.mark.parametrize(
    "code",
    [
        "solver_failed",
        "inconsistent_solution",
        "execution_timeout",
        "snapshot_corrupt",
        "invalid_input",
    ],
)
def test_a_failure_gets_its_message_from_the_catalogue(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine, code: str
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    assert database.fail(lease, code) is True
    row = job_row(owner_engine, queued)
    assert (row["status"], row["failure_code"]) == ("failed", code)
    assert row["failure_message"] == FAILURE_MESSAGES[code]  # type: ignore[index]
    assert _attempts(owner_engine, queued) == [(1, "worker-a", "failed")]


@pytest.mark.parametrize("code", ["worker_lost", "kaboom", "", "solver_failed; DROP TABLE x"])
def test_a_worker_cannot_report_any_other_failure(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine, code: str
) -> None:
    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    with pytest.raises(DBAPIError) as raised:
        database.fail(lease, code)
    assert _sqlstate(raised.value) == INVALID_PARAMETER
    assert job_row(owner_engine, queued)["status"] == "running"


def test_no_other_failure_message_can_be_stored_by_anyone(
    queued: uuid.UUID, owner_engine: Engine, worker_engine: Engine
) -> None:
    lease = _db(worker_engine).claim()
    assert lease is not None
    with pytest.raises(DBAPIError), owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE sim.jobs SET status = 'failed', failure_code = 'solver_failed', "
                "failure_message = 'Traceback: secret', lease_token = NULL, "
                "lease_expires_at = NULL, worker_id = NULL, finished_at = now() WHERE id = :id"
            ),
            {"id": queued},
        )


def test_the_catalogue_in_the_database_is_the_domains(migrated: None, owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        result = connection.execute(text("SELECT code, message FROM sim.failure_catalogue"))
        rows = {row.code: row.message for row in result}
    assert rows == {code.value: message for code, message in FAILURE_MESSAGES.items()}


def test_release_requeues_and_counts_the_attempt(
    queued: uuid.UUID, worker_engine: Engine, owner_engine: Engine
) -> None:
    database = _db(worker_engine)
    for attempt in (1, 2):
        lease = database.claim()
        assert lease is not None
        assert lease.attempt == attempt
        assert database.release(lease) is True
        assert job_row(owner_engine, queued)["status"] == "queued"
    last = database.claim()
    assert last is not None
    assert database.release(last) is True  # the last attempt: nothing left
    row = job_row(owner_engine, queued)
    assert (row["status"], row["failure_code"]) == ("failed", "worker_lost")
    assert [ending for _, _, ending in _attempts(owner_engine, queued)] == ["released"] * 3


# --- results for the API ------------------------------------------------------------------


async def test_results_are_tenant_scoped_and_immutable(
    queued: uuid.UUID,
    tenants: dict[str, uuid.UUID],
    worker_engine: Engine,
    owner_engine: Engine,
    app_async_engine: AsyncEngine,
) -> None:
    from gridwise_api.tenancy import tenant_transaction

    database = _db(worker_engine)
    lease = database.claim()
    assert lease is not None
    assert database.complete(lease, _converged()) is True

    async with tenant_transaction(app_async_engine, tenants["alpha"]) as session:
        assert (await session.execute(text("SELECT count(*) FROM sim.results"))).scalar_one() == 1
    async with tenant_transaction(app_async_engine, tenants["bravo"]) as session:
        assert (await session.execute(text("SELECT count(*) FROM sim.results"))).scalar_one() == 0
    async with app_async_engine.connect() as connection:
        assert (
            await connection.execute(text("SELECT count(*) FROM sim.results"))
        ).scalar_one() == 0

    with pytest.raises(DBAPIError) as raised, owner_engine.begin() as connection:
        connection.execute(text("UPDATE sim.results SET result_hash = repeat('0', 64)"))
    assert _sqlstate(raised.value) == CHECK_VIOLATION
