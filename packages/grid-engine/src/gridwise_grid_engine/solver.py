"""The solver boundary.

A ``PowerFlowSolver`` turns a validated ``GridModel`` into raw numbers. It knows nothing
about energisation, totals or consistency checks: ``engine.run_power_flow`` owns those, so
they hold for every solver, including a fake one in tests.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from gridwise_grid_engine.model import GridModel


@dataclass(frozen=True, slots=True, kw_only=True)
class PowerFlowOptions:
    """Numerical options of the AC Newton-Raphson power flow."""

    #: Convergence tolerance on the bus power mismatch, in MVA.
    tolerance_mva: float = 1e-8
    #: Maximum number of Newton-Raphson iterations.
    max_iterations: int = 10

    def __post_init__(self) -> None:
        if not 0 < self.tolerance_mva <= 1e-3:
            raise ValueError("tolerance_mva must be in (0, 1e-3]")
        if not 1 <= self.max_iterations <= 100:
            raise ValueError("max_iterations must be in [1, 100]")


@dataclass(frozen=True, slots=True, kw_only=True)
class RawBus:
    voltage_pu: float
    voltage_angle_degree: float
    p_mw: float
    q_mvar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RawLine:
    p_from_mw: float
    q_from_mvar: float
    p_to_mw: float
    q_to_mvar: float
    current_ka: float
    loading_percent: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RawTransformer:
    p_hv_mw: float
    q_hv_mvar: float
    p_lv_mw: float
    q_lv_mvar: float
    current_hv_ka: float
    current_lv_ka: float
    loading_percent: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RawGenerator:
    p_mw: float
    q_mvar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RawExternalGrid:
    p_mw: float
    q_mvar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RawSolution:
    """What a solver hands back. Values may be NaN for elements it did not solve.

    When ``converged`` is False the mappings must be empty; the engine does not read them.
    """

    converged: bool
    buses: Mapping[str, RawBus] = field(default_factory=dict)
    lines: Mapping[str, RawLine] = field(default_factory=dict)
    external_grids: Mapping[str, RawExternalGrid] = field(default_factory=dict)
    transformers: Mapping[str, RawTransformer] = field(default_factory=dict)
    generators: Mapping[str, RawGenerator] = field(default_factory=dict)


class PowerFlowSolver(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        """Solve a grid that has already passed ``validate_grid``.

        Must build its working state from ``grid`` on every call (never reuse a previous
        solution) and must report non-convergence as ``RawSolution(converged=False)``.
        """
        ...
