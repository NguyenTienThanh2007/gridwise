"""Worker behaviour that needs no database: classifying a bad configuration, and what the
loop does when the solver process cannot start or reports another engine version."""

import uuid
from typing import Any

import pytest

from gridwise_grid_engine import GridModel, PowerFlowOptions, RawSolution
from gridwise_grid_engine.snapshots import snapshot_hash, snapshot_text
from gridwise_worker.child import SolveRequest, solve
from gridwise_worker.database import Completion, Lease
from gridwise_worker.loop import EXIT_SOLVER_UNAVAILABLE, Worker
from gridwise_worker.settings import WorkerSettings
from gridwise_worker.supervisor import ChildStartError, Run, RunKind
from tests.support.grids import sample_grid


class _Solver:
    name = "fake"
    version = "0"

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        return RawSolution(converged=False)


def _request(configuration: str) -> SolveRequest:
    text = snapshot_text(sample_grid())
    return SolveRequest(
        job_id="j", input_document=text, input_hash=snapshot_hash(text), configuration=configuration
    )


@pytest.mark.parametrize(
    "configuration",
    [
        "not json",
        "{}",
        '{"options": {"tolerance_mva": -1, "max_iterations": 10}}',
        '{"options": {"x": 1}}',
    ],
)
def test_a_configuration_the_engine_refuses_is_invalid_input(configuration: str) -> None:
    assert solve(_request(configuration), _Solver()) == {
        "ok": False,
        "failure_code": "invalid_input",
    }


class _Database:
    def __init__(self, lease: Lease | None) -> None:
        self._lease = lease
        self.calls: list[str] = []

    def schema_revision(self) -> str:
        return "0005"

    def claim(self) -> Lease | None:
        lease, self._lease = self._lease, None
        return lease

    def heartbeat(self, lease: Lease) -> bool:
        return True

    def complete(self, lease: Lease, completion: Completion) -> bool:
        self.calls.append(f"complete:{completion.engine_version}")
        return True

    def fail(self, lease: Lease, code: str) -> bool:
        self.calls.append(f"fail:{code}")
        return True

    def release(self, lease: Lease) -> bool:
        self.calls.append("release")
        return True


class _Supervisor:
    def __init__(
        self, *, fail_start: bool = False, fail_run: bool = False, message: Any = None
    ) -> None:
        self._fail_start, self._fail_run, self._message = fail_start, fail_run, message
        self.worker: Worker | None = None

    def start(self) -> None:
        if self._fail_start:
            raise ChildStartError("no")

    def run(self, request: SolveRequest, **_: Any) -> Run:
        if self._fail_run:
            raise ChildStartError("no")
        assert self.worker is not None
        self.worker.request_stop()  # one job, then stop
        return Run(RunKind.RESULT, self._message)

    def stop(self) -> None:
        pass


def _lease() -> Lease:
    return Lease(
        job_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        token=uuid.uuid4(),
        attempt=1,
        input_document="{}",
        input_hash="0" * 64,
        configuration="{}",
        requested_engine_version="0.3.0",
    )


def _worker(database: _Database, supervisor: _Supervisor, tmp_path: Any) -> Worker:
    settings = WorkerSettings(
        _env_file=None,
        worker_database_url="postgresql+psycopg://a:b@h/d",
        worker_health_file=str(tmp_path / "alive"),
        worker_poll_seconds=0.05,
        log_format="json",
    )
    worker = Worker(settings, database, supervisor)  # type: ignore[arg-type]
    supervisor.worker = worker
    return worker


def test_a_solver_that_cannot_start_stops_the_worker_before_it_claims(tmp_path: Any) -> None:
    database = _Database(_lease())
    worker = _worker(database, _Supervisor(fail_start=True), tmp_path)
    assert worker.run() == EXIT_SOLVER_UNAVAILABLE
    assert database.calls == []
    assert database.claim() is not None  # never taken


def test_a_solver_that_cannot_restart_mid_job_releases_the_job_and_stops(tmp_path: Any) -> None:
    database = _Database(_lease())
    worker = _worker(database, _Supervisor(fail_run=True), tmp_path)
    assert worker.run() == EXIT_SOLVER_UNAVAILABLE
    assert database.calls == ["release"]


def test_another_engine_version_is_warned_about(
    tmp_path: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    message = {
        "ok": True,
        "outcome": "not_converged",
        "engine_version": "9.9.9",
        "solver_name": "fake",
        "solver_version": "0",
        "engine_fingerprint": "f" * 64,
        "result_document": None,
        "result_hash": None,
    }
    database = _Database(_lease())
    worker = _worker(database, _Supervisor(message=message), tmp_path)
    assert worker.run() == 0
    assert database.calls == ["complete:9.9.9"]
    output = capsys.readouterr().out
    assert "engine_version_differs" in output
    assert "9.9.9" in output
