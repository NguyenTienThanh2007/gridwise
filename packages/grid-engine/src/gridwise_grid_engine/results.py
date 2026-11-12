"""Power flow result models.

Sign conventions (also in docs/domain/grid-engine.md):

* bus ``p_mw`` / ``q_mvar``: net power *withdrawn* from the network at the bus
  (load minus supply). A bus that only feeds the network, such as the slack bus, is negative.
* line ``p_from_mw`` etc.: power flowing *into the line* at that end.
* external grid ``p_mw`` / ``q_mvar``: power *supplied to* the network.

``None`` always means "there is no value" (the element is de-energised). It never means
zero, and a de-energised element is never given a made-up number.
"""

from dataclasses import dataclass

from gridwise_grid_engine.errors import ErrorCode
from gridwise_grid_engine.solver import PowerFlowOptions


@dataclass(frozen=True, slots=True, kw_only=True)
class BusResult:
    bus_id: str
    energized: bool
    #: Voltage magnitude in per unit of the bus's nominal voltage.
    voltage_pu: float | None
    #: Voltage angle in degrees, relative to the external grid's angle set-point.
    voltage_angle_degree: float | None
    p_mw: float | None
    q_mvar: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class LineResult:
    line_id: str
    energized: bool
    p_from_mw: float | None
    q_from_mvar: float | None
    p_to_mw: float | None
    q_to_mvar: float | None
    #: Active power lost in the line: p_from_mw + p_to_mw.
    active_loss_mw: float | None
    #: Reactive power absorbed by the line: q_from_mvar + q_to_mvar. Negative when the
    #: line's charging exceeds its series reactive losses.
    reactive_loss_mvar: float | None
    #: The larger of the two end currents, in kiloampere.
    current_ka: float | None
    #: current_ka as a percentage of the line's thermal limit.
    loading_percent: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalGridResult:
    external_grid_id: str
    energized: bool
    p_mw: float | None
    q_mvar: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class PowerFlowTotals:
    #: Power supplied by all external grids.
    external_supply_mw: float
    external_supply_mvar: float
    #: Demand of in-service loads on energised buses.
    served_load_mw: float
    served_load_mvar: float
    #: Demand of in-service loads on de-energised buses. Reported, never silently dropped.
    unserved_load_mw: float
    unserved_load_mvar: float
    #: Sum of line losses over energised lines.
    active_losses_mw: float
    reactive_losses_mvar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class PowerFlowResult:
    """The outcome of one power flow.

    If ``converged`` is False there is no solution: every result tuple is empty, ``totals``
    is None and ``failure_code`` says why. No partial or previous values are ever present.
    """

    converged: bool
    failure_code: ErrorCode | None
    grid_hash: str
    solver_name: str
    solver_version: str
    algorithm: str
    options: PowerFlowOptions
    buses: tuple[BusResult, ...] = ()
    lines: tuple[LineResult, ...] = ()
    external_grids: tuple[ExternalGridResult, ...] = ()
    totals: PowerFlowTotals | None = None
    #: In-service buses that no external grid can reach, sorted.
    unsupplied_bus_ids: tuple[str, ...] = ()
