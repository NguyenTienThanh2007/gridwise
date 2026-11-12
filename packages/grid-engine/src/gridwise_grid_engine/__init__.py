"""GRIDWISE grid domain engine.

Importing this package does not import pandapower. The solver adapter lives in
``gridwise_grid_engine.adapters.pandapower_adapter`` and is imported explicitly by whoever
runs power flows (a worker process, never the API's request loop).
"""

from gridwise_grid_engine.engine import run_power_flow
from gridwise_grid_engine.errors import (
    ErrorCode,
    GridEngineError,
    GridValidationError,
    SolverExecutionError,
    ValidationIssue,
)
from gridwise_grid_engine.hashing import grid_hash, result_hash
from gridwise_grid_engine.model import Bus, ExternalGrid, GridModel, Line, Load
from gridwise_grid_engine.results import (
    BusResult,
    ExternalGridResult,
    LineResult,
    PowerFlowResult,
    PowerFlowTotals,
)
from gridwise_grid_engine.solver import PowerFlowOptions, PowerFlowSolver, RawSolution
from gridwise_grid_engine.topology import energized_bus_ids
from gridwise_grid_engine.validation import ensure_valid, validate_grid

__version__ = "0.1.0"

__all__ = [
    "Bus",
    "BusResult",
    "ErrorCode",
    "ExternalGrid",
    "ExternalGridResult",
    "GridEngineError",
    "GridModel",
    "GridValidationError",
    "Line",
    "LineResult",
    "Load",
    "PowerFlowOptions",
    "PowerFlowResult",
    "PowerFlowSolver",
    "PowerFlowTotals",
    "RawSolution",
    "SolverExecutionError",
    "ValidationIssue",
    "__version__",
    "energized_bus_ids",
    "ensure_valid",
    "grid_hash",
    "result_hash",
    "run_power_flow",
    "validate_grid",
]
