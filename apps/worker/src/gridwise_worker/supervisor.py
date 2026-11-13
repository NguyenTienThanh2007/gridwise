"""Runs the solver in a child process that can really be stopped.

``concurrent.futures.ProcessPoolExecutor`` cannot stop a task that has started (Python 3.13
has no way to kill its workers), so a timed-out solve would keep its CPU and memory. This
supervisor owns one child process instead, started with ``spawn`` (never ``fork``: the
parent holds database connections), and kills it with SIGKILL when it must.

The child is kept between jobs, so the solver is loaded once. After a kill or a crash a new
child is started before the next job.
"""

import enum
import multiprocessing
import time
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Any

from gridwise_worker.child import SolveRequest, child_main

_SPAWN = multiprocessing.get_context("spawn")


class RunKind(enum.Enum):
    RESULT = "result"  # the child answered
    TIMEOUT = "timeout"  # over the time limit; the child was killed
    CRASHED = "crashed"  # the child died without answering
    LEASE_LOST = "lease_lost"  # the job is no longer ours; the child was killed
    ABORTED = "aborted"  # shutdown grace ran out; the child was killed


@dataclass(frozen=True, slots=True)
class Run:
    kind: RunKind
    message: dict[str, Any] | None = None


class ChildStartError(RuntimeError):
    pass


class ChildSupervisor:
    def __init__(self, *, solver: str = "pandapower", start_timeout_seconds: float = 120.0) -> None:
        self._solver = solver
        self._start_timeout = start_timeout_seconds
        self._process: BaseProcess | None = None
        self._pipe: Connection | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._discard()
        parent, child = _SPAWN.Pipe()
        process = _SPAWN.Process(
            target=child_main, args=(child, self._solver), name="gridwise-solver", daemon=True
        )
        process.start()
        child.close()
        self._process, self._pipe = process, parent
        if not parent.poll(self._start_timeout):
            self.kill()
            raise ChildStartError("the solver process did not start in time")
        try:
            parent.recv()
        except EOFError as error:
            self.kill()
            raise ChildStartError("the solver process exited while starting") from error

    def run(
        self,
        request: SolveRequest,
        *,
        timeout_seconds: float,
        tick_seconds: float,
        on_tick: Callable[[], bool],
        should_abort: Callable[[], bool],
    ) -> Run:
        """Solve one request. ``on_tick`` is called every ``tick_seconds`` (the heartbeat);
        returning False means the job is no longer ours."""
        self.start()
        assert self._pipe is not None  # noqa: S101  (started above)
        try:
            self._pipe.send(request)
        except (BrokenPipeError, OSError):
            self._discard()
            return Run(RunKind.CRASHED)

        started = time.monotonic()
        deadline = started + timeout_seconds
        next_tick = started + tick_seconds
        while True:
            now = time.monotonic()
            if now >= deadline:
                self.kill()
                return Run(RunKind.TIMEOUT)
            wait = max(0.0, min(deadline, next_tick, now + 0.5) - now)
            try:
                ready = self._pipe.poll(wait)
                if ready:
                    return Run(RunKind.RESULT, self._pipe.recv())
            except (EOFError, OSError):
                self._discard()
                return Run(RunKind.CRASHED)
            if self._process is None or not self._process.is_alive():
                self._discard()
                return Run(RunKind.CRASHED)
            if should_abort():
                self.kill()
                return Run(RunKind.ABORTED)
            if time.monotonic() >= next_tick:
                next_tick += tick_seconds
                if not on_tick():
                    self.kill()
                    return Run(RunKind.LEASE_LOST)

    def kill(self) -> None:
        """SIGKILL the child and wait for it to be gone."""
        if self._process is not None and self._process.is_alive():
            self._process.kill()
            self._process.join(10)
        self._discard()

    def stop(self) -> None:
        """Let an idle child exit on its own (closing the pipe ends its loop)."""
        if self._pipe is not None:
            self._pipe.close()
        if self._process is not None:
            self._process.join(5)
        self.kill()

    def _discard(self) -> None:
        if self._pipe is not None:
            self._pipe.close()
        if self._process is not None:
            if self._process.is_alive():
                self._process.kill()
            self._process.join(10)
            self._process.close()
        self._process, self._pipe = None, None
