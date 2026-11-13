"""Why a job failed: stable codes, and the only messages ever stored or shown.

A failure message comes from this catalogue, never from an exception: exception text may
quote input data, paths or configuration. Details go to the worker's log, keyed by job id.

None of these failures is retried. A job is put back in the queue only when its worker was
lost (its lease expired), and ``worker_lost`` is what remains after the last attempt.
"""

from enum import StrEnum


class FailureCode(StrEnum):
    SOLVER_FAILED = "solver_failed"
    INCONSISTENT_SOLUTION = "inconsistent_solution"
    EXECUTION_TIMEOUT = "execution_timeout"
    WORKER_LOST = "worker_lost"
    SNAPSHOT_CORRUPT = "snapshot_corrupt"
    INVALID_INPUT = "invalid_input"


FAILURE_MESSAGES: dict[FailureCode, str] = {
    FailureCode.SOLVER_FAILED: "The power flow solver stopped with an error.",
    FailureCode.INCONSISTENT_SOLUTION: (
        "The solver returned a solution that failed the engine's consistency checks. "
        "It was not stored."
    ),
    FailureCode.EXECUTION_TIMEOUT: "The computation did not finish within the time limit.",
    FailureCode.WORKER_LOST: "The worker running this job stopped responding, on every attempt.",
    FailureCode.SNAPSHOT_CORRUPT: "The stored input did not match its hash and was not used.",
    FailureCode.INVALID_INPUT: "The stored input is not a valid grid for this engine version.",
}


def failure_message(code: FailureCode) -> str:
    return FAILURE_MESSAGES[code]
