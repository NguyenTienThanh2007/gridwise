"""Solvers for worker tests. Loaded in the worker's child process through the
``worker_solver`` test hook ("tests.support.worker_solvers:<Name>")."""

import os
import time

from gridwise_grid_engine import GridModel, PowerFlowOptions, RawSolution


class _Base:
    name = "test-solver"
    version = "0"


class Sleeping(_Base):
    """Never finishes on its own: only a kill stops it. Writes its pid first."""

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        marker = os.environ.get("GRIDWISE_TEST_PID_FILE")
        if marker:
            with open(marker, "w") as handle:
                handle.write(str(os.getpid()))
        while True:
            time.sleep(1)


class Dying(_Base):
    """The process ends abruptly, as after an out-of-memory kill."""

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        os._exit(137)


class Raising(_Base):
    """An unexpected error whose message must never reach the database."""

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        raise RuntimeError("SECRET-DETAIL /etc/passwd connection=postgres://x:y@h")


class NotConverging(_Base):
    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        return RawSolution(converged=False)


class Slow(_Base):
    """Answers after a few seconds, with the real solver."""

    def __init__(self) -> None:
        from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver

        self._real = PandapowerSolver()
        self.name = self._real.name
        self.version = self._real.version

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        time.sleep(float(os.environ.get("GRIDWISE_TEST_SOLVE_SECONDS", "3")))
        return self._real.solve(grid, options)


class FailsToStart(_Base):
    """The solver cannot even be built: the child process dies before it is ready."""

    def __init__(self) -> None:
        raise RuntimeError("cannot start")

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:  # pragma: no cover
        raise AssertionError
