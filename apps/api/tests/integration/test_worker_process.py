"""The worker as processes: real child processes, real signals, a real database.

Marked ``worker``: these start processes and depend on operating-system process semantics,
which CI checks on Linux.
"""

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.simulation.failures import FAILURE_MESSAGES
from gridwise_grid_engine import result_hash, run_power_flow
from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
from gridwise_grid_engine.snapshots import grid_from_snapshot
from gridwise_worker.database import WorkerDatabase
from gridwise_worker.loop import EXIT_OK, EXIT_SCHEMA_MISMATCH, Worker
from gridwise_worker.settings import WorkerSettings
from gridwise_worker.supervisor import ChildSupervisor
from tests.integration.conftest import TestDatabase
from tests.support.simulations import job_row, service, stored_grid

pytestmark = [pytest.mark.integration, pytest.mark.worker]

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = API_ROOT.parents[1]
SOLVERS = "tests.support.worker_solvers"


def _settings(database_url: str, tmp_path: Path, **overrides: Any) -> WorkerSettings:
    values: dict[str, Any] = {
        "worker_database_url": database_url,
        "worker_id": "test-worker",
        "worker_job_timeout_seconds": 60,
        "worker_lease_seconds": 6,
        "worker_heartbeat_seconds": 1,
        "worker_poll_seconds": 0.2,
        "worker_max_backoff_seconds": 1,
        "worker_shutdown_grace_seconds": 2,
        "worker_health_file": str(tmp_path / "alive"),
        "log_format": "json",
        **overrides,
    }
    return WorkerSettings(_env_file=None, **values)


@contextmanager
def running_worker(settings: WorkerSettings, solver: str = "pandapower") -> Iterator[Worker]:
    """A worker loop in a background thread (its solver child is a real process)."""
    engine = create_engine(settings.worker_database_url.get_secret_value(), hide_parameters=True)
    worker = Worker(
        settings,
        WorkerDatabase(
            engine, worker_id=settings.worker_id, lease_seconds=settings.worker_lease_seconds
        ),
        ChildSupervisor(solver=solver),
    )
    exit_codes: list[int] = []
    thread = threading.Thread(target=lambda: exit_codes.append(worker.run()), daemon=True)
    thread.start()
    try:
        yield worker
    finally:
        worker.request_stop()
        thread.join(60)
        engine.dispose()
    assert not thread.is_alive()
    assert exit_codes == [EXIT_OK]


def _wait(predicate: Callable[[], bool], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise AssertionError("condition not reached in time")


def _status(owner: Engine, job_id: uuid.UUID) -> str:
    return str(job_row(owner, job_id)["status"])


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
async def job(tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine) -> uuid.UUID:
    grid_id = await stored_grid(app_async_engine, tenants["alpha"])
    return (await service(app_async_engine).submit(tenants["alpha"], grid_id)).job.id


# --- in-process loop, real child ----------------------------------------------------------


def test_a_job_is_solved_and_the_result_reproduces(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    with running_worker(_settings(database.worker_url, tmp_path)):
        _wait(lambda: _status(owner_engine, job) == "completed")
    row = job_row(owner_engine, job)
    assert (row["outcome"], row["solver_name"], row["executed_engine_version"]) == (
        "converged",
        "pandapower",
        "0.3.0",
    )
    with owner_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT r.result_hash, s.document FROM sim.results r "
                "JOIN sim.jobs j ON j.id = r.job_id "
                "JOIN sim.snapshots s ON s.id = j.input_snapshot_id WHERE r.job_id = :id"
            ),
            {"id": job},
        ).one()
    # Recomputed here, from the stored input alone: the same result.
    recomputed = run_power_flow(grid_from_snapshot(stored.document), PandapowerSolver())
    assert result_hash(recomputed) == stored.result_hash
    assert (tmp_path / "alive").exists()


def test_non_convergence_is_completed_without_a_result(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    with running_worker(_settings(database.worker_url, tmp_path), f"{SOLVERS}:NotConverging"):
        _wait(lambda: _status(owner_engine, job) == "completed")
    assert job_row(owner_engine, job)["outcome"] == "not_converged"
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sim.results")).scalar_one() == 0


def test_an_unexpected_error_is_a_coded_failure_and_its_text_goes_nowhere(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    with running_worker(_settings(database.worker_url, tmp_path), f"{SOLVERS}:Raising"):
        _wait(lambda: _status(owner_engine, job) == "failed")
    row = job_row(owner_engine, job)
    assert row["failure_code"] == "solver_failed"
    assert row["failure_message"] == FAILURE_MESSAGES["solver_failed"]  # type: ignore[index]
    assert "SECRET" not in repr(row)
    assert row["attempt"] == 1  # not retried


def test_a_timeout_kills_the_solver_process_and_is_not_retried(
    job: uuid.UUID,
    database: TestDatabase,
    owner_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid_file = tmp_path / "solver.pid"
    monkeypatch.setenv("GRIDWISE_TEST_PID_FILE", str(pid_file))
    settings = _settings(database.worker_url, tmp_path, worker_job_timeout_seconds=3)
    with running_worker(settings, f"{SOLVERS}:Sleeping"):
        _wait(lambda: pid_file.exists())
        pid = int(pid_file.read_text())
        assert _alive(pid)
        _wait(lambda: _status(owner_engine, job) == "failed", timeout=30)
        _wait(lambda: not _alive(pid), timeout=10)  # really gone, not left running
    row = job_row(owner_engine, job)
    assert (row["failure_code"], row["attempt"]) == ("execution_timeout", 1)


def test_a_dying_solver_process_is_retried_then_reported_lost(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    with running_worker(_settings(database.worker_url, tmp_path), f"{SOLVERS}:Dying"):
        _wait(lambda: _status(owner_engine, job) == "failed", timeout=90)
    row = job_row(owner_engine, job)
    assert (row["failure_code"], row["attempt"]) == ("worker_lost", 3)
    with owner_engine.connect() as connection:
        endings = (
            connection.execute(
                text("SELECT ended_by FROM sim.job_attempts WHERE job_id = :id ORDER BY attempt"),
                {"id": job},
            )
            .scalars()
            .all()
        )
    assert endings == ["released", "released", "released"]


def test_an_unreachable_database_is_waited_for_not_fatal(tmp_path: Path) -> None:
    settings = _settings("postgresql+psycopg://nobody:nothing@127.0.0.1:1/none", tmp_path)
    engine = create_engine(settings.worker_database_url.get_secret_value())
    worker = Worker(
        settings, WorkerDatabase(engine, worker_id="w", lease_seconds=6), ChildSupervisor()
    )
    codes: list[int] = []
    thread = threading.Thread(target=lambda: codes.append(worker.run()), daemon=True)
    thread.start()
    time.sleep(2.5)  # several failed attempts with back-off
    assert thread.is_alive()
    worker.request_stop()
    thread.join(10)
    assert codes == [EXIT_OK]


def test_a_schema_it_was_not_built_for_stops_the_worker(
    alembic_config: Any, database: TestDatabase, tmp_path: Path
) -> None:
    from alembic import command

    command.upgrade(alembic_config, "0003")  # the worker functions do not exist yet
    with running_worker_expecting(_settings(database.worker_url, tmp_path)) as code:
        assert code == EXIT_SCHEMA_MISMATCH


@contextmanager
def running_worker_expecting(settings: WorkerSettings) -> Iterator[int]:
    engine = create_engine(settings.worker_database_url.get_secret_value())
    try:
        worker = Worker(
            settings, WorkerDatabase(engine, worker_id="w", lease_seconds=6), ChildSupervisor()
        )
        yield worker.run()
    finally:
        engine.dispose()


def test_the_health_check_reports_a_stalled_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gridwise_worker import healthcheck

    alive = tmp_path / "alive"
    monkeypatch.setenv("GRIDWISE_WORKER_DATABASE_URL", "postgresql+psycopg://a:b@h/d")
    monkeypatch.setenv("GRIDWISE_WORKER_HEALTH_FILE", str(alive))
    monkeypatch.setenv("GRIDWISE_WORKER_HEALTH_MAX_AGE_SECONDS", "5")
    assert healthcheck.main() == 1  # never started
    alive.touch()
    assert healthcheck.main() == 0
    old = time.time() - 60
    os.utime(alive, (old, old))
    assert healthcheck.main() == 1


# --- the real command, with signals -------------------------------------------------------


def _environment(database: TestDatabase, tmp_path: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            str(path)
            for path in (
                REPO_ROOT / "apps/worker/src",
                API_ROOT / "src",
                API_ROOT,
                REPO_ROOT / "packages/grid-engine/src",
            )
        ),
        "GRIDWISE_WORKER_DATABASE_URL": database.worker_url,
        "GRIDWISE_WORKER_LEASE_SECONDS": "6",
        "GRIDWISE_WORKER_HEARTBEAT_SECONDS": "1",
        "GRIDWISE_WORKER_POLL_SECONDS": "0.2",
        "GRIDWISE_WORKER_SHUTDOWN_GRACE_SECONDS": "2",
        "GRIDWISE_WORKER_HEALTH_FILE": str(tmp_path / "alive"),
        "GRIDWISE_LOG_FORMAT": "json",
        **extra,
    }


def _start(environment: dict[str, str], tmp_path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "gridwise_worker"],
        env=environment,
        cwd=API_ROOT,
        stdout=(tmp_path / "worker.log").open("w"),
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_sigterm_while_idle_exits_cleanly(
    migrated: None, database: TestDatabase, tmp_path: Path
) -> None:
    process = _start(_environment(database, tmp_path), tmp_path)
    _wait(lambda: (tmp_path / "alive").exists())
    process.send_signal(signal.SIGTERM)
    assert process.wait(30) == 0
    log = (tmp_path / "worker.log").read_text()
    assert '"event": "worker_stopped"' in log
    assert database.worker_url not in log


def test_sigterm_lets_a_short_job_finish(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    environment = _environment(
        database,
        tmp_path,
        GRIDWISE_WORKER_SOLVER=f"{SOLVERS}:Slow",
        GRIDWISE_TEST_SOLVE_SECONDS="2",
        GRIDWISE_WORKER_SHUTDOWN_GRACE_SECONDS="20",
    )
    process = _start(environment, tmp_path)
    _wait(lambda: _status(owner_engine, job) == "running")
    process.send_signal(signal.SIGTERM)
    assert process.wait(60) == 0
    assert _status(owner_engine, job) == "completed"


def test_sigterm_beyond_the_grace_period_releases_the_job(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    pid_file = tmp_path / "solver.pid"
    environment = _environment(
        database,
        tmp_path,
        GRIDWISE_WORKER_SOLVER=f"{SOLVERS}:Sleeping",
        GRIDWISE_TEST_PID_FILE=str(pid_file),
    )
    process = _start(environment, tmp_path)
    _wait(lambda: pid_file.exists())
    solver_pid = int(pid_file.read_text())
    process.send_signal(signal.SIGTERM)
    assert process.wait(30) == 0
    row = job_row(owner_engine, job)
    assert (row["status"], row["attempt"]) == ("queued", 1)
    with owner_engine.connect() as connection:
        ending = connection.execute(
            text("SELECT ended_by FROM sim.job_attempts WHERE job_id = :id"), {"id": job}
        ).scalar_one()
    assert ending == "released"
    _wait(lambda: not _alive(solver_pid), timeout=10)


def test_a_killed_worker_is_recovered_by_the_next_one(
    job: uuid.UUID, database: TestDatabase, owner_engine: Engine, tmp_path: Path
) -> None:
    """SIGKILL: no clean-up runs. The lease expires, the next worker takes the job over, and
    the orphaned solver process notices its parent is gone and exits."""
    pid_file = tmp_path / "solver.pid"
    first = _start(
        _environment(
            database,
            tmp_path,
            GRIDWISE_WORKER_SOLVER=f"{SOLVERS}:Sleeping",
            GRIDWISE_TEST_PID_FILE=str(pid_file),
        ),
        tmp_path,
    )
    _wait(lambda: pid_file.exists())
    orphan = int(pid_file.read_text())
    first.kill()
    first.wait(10)
    _wait(lambda: not _alive(orphan), timeout=15)
    assert _status(owner_engine, job) == "running"  # nobody has noticed yet

    second = _start(_environment(database, tmp_path), tmp_path)
    try:
        _wait(lambda: _status(owner_engine, job) == "completed", timeout=90)
    finally:
        second.send_signal(signal.SIGTERM)
        second.wait(30)
    row = job_row(owner_engine, job)
    assert row["attempt"] == 2
    with owner_engine.connect() as connection:
        endings = (
            connection.execute(
                text("SELECT ended_by FROM sim.job_attempts WHERE job_id = :id ORDER BY attempt"),
                {"id": job},
            )
            .scalars()
            .all()
        )
    assert endings == ["lease_expired", "completed"]


def test_the_worker_parent_never_loads_the_solver(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        "import gridwise_worker.__main__, gridwise_worker.loop, gridwise_worker.supervisor\n"
        "import gridwise_worker.database, gridwise_worker.healthcheck\n"
        "print(sorted(m for m in ('pandapower', 'pandas', 'numpy', 'scipy') if m in sys.modules))\n"
    )
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            str(path)
            for path in (
                REPO_ROOT / "apps/worker/src",
                API_ROOT / "src",
                REPO_ROOT / "packages/grid-engine/src",
            )
        ),
    }
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], env=environment, capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]"
