"""The worker loop: claim a job, solve it in the child, record the outcome.

Rules (decision 0011):

* The database decides everything about a job; the worker only reports. A call about a job
  whose lease is no longer ours returns False, and the worker drops what it has.
* A failure caused by the input is reported once and never retried. A child that died is
  handed back (release): the database requeues the job while attempts remain.
* On SIGTERM the worker stops claiming. The current job may finish within the grace period;
  after that the child is killed and the job is released.
* While the database is unreachable the worker backs off and tries again.
* Logs carry the job id, organisation and attempt, never input data. The database gets
  failure codes only.
"""

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from sqlalchemy.exc import InterfaceError, OperationalError

from gridwise_api.logging import get_logger
from gridwise_api.schema_version import EXPECTED_SCHEMA_REVISION
from gridwise_worker.child import SolveRequest
from gridwise_worker.database import Completion, Lease, WorkerDatabase
from gridwise_worker.settings import WorkerSettings
from gridwise_worker.supervisor import ChildStartError, ChildSupervisor, RunKind

logger = get_logger("gridwise_worker")

_UNAVAILABLE = (OperationalError, InterfaceError)
T = TypeVar("T")

#: Exit codes of ``run``.
EXIT_OK = 0
EXIT_SCHEMA_MISMATCH = 2
EXIT_SOLVER_UNAVAILABLE = 3


class Worker:
    def __init__(
        self,
        settings: WorkerSettings,
        database: WorkerDatabase,
        supervisor: ChildSupervisor,
    ) -> None:
        self._settings = settings
        self._db = database
        self._supervisor = supervisor
        self._stop = threading.Event()
        self._stop_requested_at: float | None = None
        self._solver_unavailable = False
        self._health = Path(settings.worker_health_file)

    # --- control ---

    def request_stop(self) -> None:
        if not self._stop.is_set():
            self._stop_requested_at = time.monotonic()
            self._stop.set()
            logger.info("worker_stopping", worker_id=self._settings.worker_id)

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def _grace_over(self) -> bool:
        return (
            self._stop_requested_at is not None
            and time.monotonic() - self._stop_requested_at
            >= self._settings.worker_shutdown_grace_seconds
        )

    def _touch(self) -> None:
        try:
            self._health.touch()
        except OSError:
            logger.warning("health_file_unwritable")

    # --- database, with back-off while it is unavailable ---

    def _wait_for_database(self, call: Callable[[], T], *, until: float | None = None) -> T | None:
        backoff = self._settings.worker_poll_seconds
        while True:
            try:
                return call()
            except _UNAVAILABLE as error:
                logger.warning(
                    "database_unavailable",
                    error_type=type(error.orig).__name__ if error.orig else type(error).__name__,
                    retry_in_seconds=round(backoff, 1),
                )
            if until is not None:
                # Reporting on a held job: keep trying while the lease can still be ours,
                # also during shutdown.
                if time.monotonic() + backoff > until:
                    return None
                time.sleep(backoff)
            elif self._stop.wait(backoff):
                return None
            backoff = min(backoff * 2, self._settings.worker_max_backoff_seconds)

    # --- the loop ---

    def run(self) -> int:
        revision = self._wait_for_database(self._db.schema_revision)
        if self.stopping:
            return EXIT_OK
        if revision != EXPECTED_SCHEMA_REVISION:
            logger.error(
                "schema_mismatch", schema_revision=revision, expected=EXPECTED_SCHEMA_REVISION
            )
            return EXIT_SCHEMA_MISMATCH
        try:
            self._supervisor.start()
        except ChildStartError:
            # Nothing was claimed: the process exits and its supervisor (Compose) restarts it.
            logger.error("solver_process_unavailable", worker_id=self._settings.worker_id)
            return EXIT_SOLVER_UNAVAILABLE
        logger.info("worker_started", worker_id=self._settings.worker_id)
        try:
            while not self.stopping:
                self._touch()
                lease = self._wait_for_database(self._db.claim)
                if lease is None:
                    self._stop.wait(self._settings.worker_poll_seconds)
                    continue
                self._process(lease)
        finally:
            self._supervisor.stop()
            logger.info("worker_stopped", worker_id=self._settings.worker_id)
        return EXIT_SOLVER_UNAVAILABLE if self._solver_unavailable else EXIT_OK

    def _process(self, lease: Lease) -> None:
        log = logger.bind(
            job_id=str(lease.job_id),
            organization_id=str(lease.organization_id),
            attempt=lease.attempt,
        )
        log.info("job_claimed")

        def heartbeat() -> bool:
            self._touch()
            try:
                return self._db.heartbeat(lease)
            except _UNAVAILABLE:
                # Keep computing: if the lease runs out meanwhile, completion will say so.
                log.warning("heartbeat_failed")
                return True

        try:
            run = self._supervisor.run(
                SolveRequest(
                    job_id=str(lease.job_id),
                    input_document=lease.input_document,
                    input_hash=lease.input_hash,
                    configuration=lease.configuration,
                ),
                timeout_seconds=self._settings.worker_job_timeout_seconds,
                tick_seconds=self._settings.worker_heartbeat_seconds,
                on_tick=heartbeat,
                should_abort=self._grace_over,
            )
        except ChildStartError:
            # No solver process can be started: give the job back and stop this worker.
            until = time.monotonic() + self._settings.worker_lease_seconds
            released = self._wait_for_database(lambda: self._db.release(lease), until=until)
            log.error("solver_process_unavailable", released=bool(released))
            self._solver_unavailable = True
            self.request_stop()
            return
        # A write is worth retrying only while our lease can still be valid.
        until = time.monotonic() + self._settings.worker_lease_seconds

        if run.kind is RunKind.RESULT and run.message and run.message.get("ok"):
            completion = Completion(
                outcome=run.message["outcome"],
                engine_version=run.message["engine_version"],
                solver_name=run.message["solver_name"],
                solver_version=run.message["solver_version"],
                engine_fingerprint=run.message["engine_fingerprint"],
                result_document=run.message["result_document"],
                result_hash=run.message["result_hash"],
            )
            written = self._wait_for_database(
                lambda: self._db.complete(lease, completion), until=until
            )
            event = "job_completed" if written else "job_result_discarded"
            log.info(event, outcome=completion.outcome)
            if (
                lease.requested_engine_version is not None
                and lease.requested_engine_version != completion.engine_version
            ):
                # Recorded on the job either way; said here so an operator notices.
                log.warning(
                    "engine_version_differs",
                    requested_engine_version=lease.requested_engine_version,
                    executed_engine_version=completion.engine_version,
                )
        elif run.kind is RunKind.RESULT:
            code = str((run.message or {}).get("failure_code", "solver_failed"))
            written = self._wait_for_database(lambda: self._db.fail(lease, code), until=until)
            log.info("job_failed" if written else "job_failure_discarded", failure_code=code)
        elif run.kind is RunKind.TIMEOUT:
            written = self._wait_for_database(
                lambda: self._db.fail(lease, "execution_timeout"), until=until
            )
            log.warning("job_timed_out", recorded=bool(written))
        elif run.kind is RunKind.CRASHED:
            written = self._wait_for_database(lambda: self._db.release(lease), until=until)
            log.error("solver_process_died", released=bool(written))
        elif run.kind is RunKind.ABORTED:
            written = self._wait_for_database(lambda: self._db.release(lease), until=until)
            log.warning("job_released_at_shutdown", released=bool(written))
        else:
            log.warning("lease_lost")
