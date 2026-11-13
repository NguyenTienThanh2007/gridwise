"""Job lifecycle: the states a simulation job can be in, and the legal moves between them.

    queued ──claim──▶ running ──▶ completed (outcome: converged | not_converged)
      │   ◀──lease expired──┘ └──▶ failed (failure_code)
      └──cancel──▶ cancelled

* ``running -> running`` is a heartbeat: the worker extends its lease.
* ``running -> queued`` happens only when a worker's lease expired (the worker was lost);
  the attempt is recorded. Deterministic outcomes are never retried.
* Terminal states never change again.

The same table is stored in the database (``sim.job_transitions``) and enforced there by a
trigger for every role; a test keeps the two identical.
"""

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Outcome(StrEnum):
    """How a completed job ended. Only ``converged`` comes with numerical results."""

    CONVERGED = "converged"
    NOT_CONVERGED = "not_converged"


TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})

TRANSITIONS: frozenset[tuple[JobStatus, JobStatus]] = frozenset(
    {
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.QUEUED, JobStatus.CANCELLED),
        (JobStatus.RUNNING, JobStatus.RUNNING),
        (JobStatus.RUNNING, JobStatus.COMPLETED),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.QUEUED),
    }
)

#: The only move the API's runtime role may make. Everything else belongs to the worker.
API_TRANSITIONS: frozenset[tuple[JobStatus, JobStatus]] = frozenset(
    {(JobStatus.QUEUED, JobStatus.CANCELLED)}
)


class IllegalTransitionError(ValueError):
    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"a job cannot go from {current.value} to {target.value}")


def is_legal(current: JobStatus, target: JobStatus) -> bool:
    return (current, target) in TRANSITIONS


def require_transition(current: JobStatus, target: JobStatus) -> None:
    if not is_legal(current, target):
        raise IllegalTransitionError(current, target)
