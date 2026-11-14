"""Reproduce finished simulations and record whether their results hold.

    python -m gridwise_worker.reproduce --pending [--limit 50]
    python -m gridwise_worker.reproduce --organization ORG --job JOB

For each job: read its stored input, verify the snapshot's hash, solve it again in the
solver child with the job's exact configuration, and record the outcome. The database
decides the verdict from what is stored (``sim.record_reproduction``):

    match                         same outcome and the same result_hash
    mismatch                      different, with the same engine and solver versions
    differs_after_engine_change   different, with another engine or solver version
    result_missing                completed and converged, but no stored result
    not_reproducible              the job did not complete (failed or cancelled)
    snapshot_corrupt              the stored input does not match its hash
    reproduction_failed           the reproduction itself could not finish

Runs with the worker's credentials and the worker's solver process; nothing here runs in an
HTTP request. Prints one JSON line per job. Exits 1 if any verdict is an integrity problem
(mismatch, result_missing, snapshot_corrupt, reproduction_failed), otherwise 0.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from uuid import UUID

from gridwise_api.logging import configure_logging, get_logger
from gridwise_worker.child import SolveRequest
from gridwise_worker.database import WorkerDatabase, connect
from gridwise_worker.settings import WorkerSettings
from gridwise_worker.supervisor import ChildSupervisor, RunKind

logger = get_logger("gridwise_worker.reproduce")

ALARMS = frozenset({"mismatch", "result_missing", "snapshot_corrupt", "reproduction_failed"})


def reproduce_job(
    database: WorkerDatabase,
    supervisor: ChildSupervisor,
    organization_id: UUID,
    job_id: UUID,
    *,
    timeout_seconds: float,
) -> str | None:
    """Reproduce one job and return the recorded verdict (None: no such job here)."""
    job = database.reproduction_input(organization_id, job_id)
    if job is None:
        return None
    nothing = {
        "outcome": None,
        "result_hash": None,
        "engine_version": None,
        "solver_name": None,
        "solver_version": None,
    }
    solvable = job.status == "completed" and not (
        job.outcome == "converged" and job.stored_result_hash is None
    )
    if not solvable:
        # The database records not_reproducible or result_missing.
        return database.record_reproduction(organization_id, job_id, **nothing, problem=None)

    run = supervisor.run(
        SolveRequest(
            job_id=str(job_id),
            input_document=job.input_document,
            input_hash=job.input_hash,
            configuration=job.configuration,
        ),
        timeout_seconds=timeout_seconds,
        tick_seconds=timeout_seconds,
        on_tick=lambda: True,
        should_abort=lambda: False,
    )
    message = run.message or {}
    if run.kind is not RunKind.RESULT or not message.get("ok"):
        problem = (
            "snapshot_corrupt"
            if message.get("failure_code") == "snapshot_corrupt"
            else "reproduction_failed"
        )
        return database.record_reproduction(organization_id, job_id, **nothing, problem=problem)
    return database.record_reproduction(
        organization_id,
        job_id,
        outcome=message["outcome"],
        result_hash=message["result_hash"],
        engine_version=message["engine_version"],
        solver_name=message["solver_name"],
        solver_version=message["solver_version"],
        problem=None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gridwise_worker.reproduce",
        description="Reproduce finished simulations and record whether their results hold.",
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--pending", action="store_true", help="completed jobs never reproduced")
    which.add_argument("--job", type=UUID, help="one job (needs --organization)")
    parser.add_argument("--organization", type=UUID, help="the job's organisation")
    parser.add_argument("--limit", type=int, default=50, help="with --pending: at most this many")
    arguments = parser.parse_args(argv)
    if arguments.job is not None and arguments.organization is None:
        parser.error("--job needs --organization")

    settings = WorkerSettings()
    configure_logging(settings)
    engine = connect(settings)
    database = WorkerDatabase(
        engine, worker_id=settings.worker_id, lease_seconds=settings.worker_lease_seconds
    )
    supervisor = ChildSupervisor(solver=settings.worker_solver)
    alarms = 0
    try:
        jobs = (
            [(arguments.job, arguments.organization)]
            if arguments.job is not None
            else database.reproduction_candidates(arguments.limit)
        )
        for job_id, organization_id in jobs:
            verdict = reproduce_job(
                database,
                supervisor,
                organization_id,
                job_id,
                timeout_seconds=settings.worker_job_timeout_seconds,
            )
            line = {
                "job_id": str(job_id),
                "organization_id": str(organization_id),
                "verdict": verdict,
            }
            print(json.dumps(line, sort_keys=True))  # noqa: T201  (the command's output)
            if verdict is None or verdict in ALARMS:
                alarms += 1
                logger.error("reproduction_alarm", **line)
    finally:
        supervisor.stop()
        engine.dispose()
    return 1 if alarms else 0


if __name__ == "__main__":
    sys.exit(main())
