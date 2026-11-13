"""The solver process. The only worker module that imports the solver adapter.

Started with the ``spawn`` method: it shares no memory, threads or database connections with
the parent. It receives an input snapshot and a configuration, verifies the snapshot's hash,
solves it, and sends back the outcome. Failures are reported as a code from the catalogue,
never as exception text; the exception type and traceback go to this process's log.
"""

import json
import os
import threading
import time
import traceback
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any

from gridwise_grid_engine import (
    GridValidationError,
    PowerFlowOptions,
    SolverExecutionError,
    __version__,
    result_hash,
    run_power_flow,
)
from gridwise_grid_engine.errors import ErrorCode
from gridwise_grid_engine.fingerprint import engine_fingerprint
from gridwise_grid_engine.result_documents import result_document_text
from gridwise_grid_engine.snapshots import SnapshotError, grid_from_snapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class SolveRequest:
    job_id: str
    input_document: str
    input_hash: str
    configuration: str


def _options(configuration: str) -> PowerFlowOptions:
    document = json.loads(configuration)
    return PowerFlowOptions(**document["options"])


def solve(request: SolveRequest, solver: Any) -> dict[str, Any]:
    """Compute one job. Always returns a message; never raises."""
    try:
        grid = grid_from_snapshot(request.input_document, expected_hash=request.input_hash)
    except SnapshotError:
        return {"ok": False, "failure_code": "snapshot_corrupt"}
    try:
        options = _options(request.configuration)
        result = run_power_flow(grid, solver, options)
    except GridValidationError:
        return {"ok": False, "failure_code": "invalid_input"}
    except SolverExecutionError as error:
        code = (
            "inconsistent_solution"
            if error.code is ErrorCode.INCONSISTENT_SOLUTION
            else "solver_failed"
        )
        return {"ok": False, "failure_code": code}
    except Exception:
        traceback.print_exc()
        return {"ok": False, "failure_code": "solver_failed"}

    common = {
        "ok": True,
        "engine_version": __version__,
        "solver_name": solver.name,
        "solver_version": solver.version,
        "engine_fingerprint": engine_fingerprint(
            engine_version=__version__,
            solver_name=solver.name,
            solver_version=solver.version,
            options=options,
        ),
    }
    if not result.converged:
        return {**common, "outcome": "not_converged", "result_document": None, "result_hash": None}
    return {
        **common,
        "outcome": "converged",
        "result_document": result_document_text(result),
        "result_hash": result_hash(result),
    }


def _exit_when_orphaned(parent_pid: int) -> None:
    """If the parent dies (even by SIGKILL) this process must not keep computing."""

    def watch() -> None:
        while True:
            if os.getppid() != parent_pid:
                os._exit(1)
            time.sleep(1)

    threading.Thread(target=watch, name="orphan-watch", daemon=True).start()


def child_main(connection: Connection, solver_factory: str = "pandapower") -> None:
    """Loop: receive a request, send a response. Ends when the parent closes the pipe."""
    _exit_when_orphaned(os.getppid())
    if solver_factory == "pandapower":
        from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver

        solver: Any = PandapowerSolver()
    else:  # test hooks: a module path "package.module:attribute" building a solver
        module_name, _, attribute = solver_factory.partition(":")
        module = __import__(module_name, fromlist=[attribute])
        solver = getattr(module, attribute)()
    connection.send({"ready": True})
    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        connection.send(solve(request, solver))
