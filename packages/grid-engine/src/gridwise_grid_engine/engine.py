"""run_power_flow: the one entry point for solving a grid.

    validate -> solve -> check the solution -> typed result

The checks after solving are what make the result trustworthy regardless of solver:

* every energised element must have finite values;
* every de-energised element must have none (it gets ``None``, never a number);
* supply must equal served load plus losses, for active and reactive power.

A solution that fails a check is rejected with ``INCONSISTENT_SOLUTION`` rather than
returned. A power flow that does not converge is an expected outcome, returned as a result
with ``converged=False`` and no values at all.
"""

import math

from gridwise_grid_engine.errors import ErrorCode, GridEngineError, SolverExecutionError
from gridwise_grid_engine.hashing import grid_hash
from gridwise_grid_engine.model import GridModel
from gridwise_grid_engine.results import (
    BusResult,
    ExternalGridResult,
    LineResult,
    PowerFlowResult,
    PowerFlowTotals,
)
from gridwise_grid_engine.solver import PowerFlowOptions, PowerFlowSolver, RawSolution
from gridwise_grid_engine.topology import energized_bus_ids
from gridwise_grid_engine.validation import ensure_valid

ALGORITHM = "newton_raphson"

#: Floor of the power-balance check, in MW / MVAr.
BALANCE_TOLERANCE_FLOOR = 1e-6


def balance_tolerance(options: PowerFlowOptions, energized_bus_count: int) -> float:
    """Each bus may be off by the solver tolerance; allow that to add up, with margin."""
    return max(BALANCE_TOLERANCE_FLOOR, 100 * options.tolerance_mva * energized_bus_count)


def _inconsistent(message: str) -> SolverExecutionError:
    return SolverExecutionError(ErrorCode.INCONSISTENT_SOLUTION, message)


def _require_finite(owner: str, **values: float) -> None:
    for name, value in values.items():
        if not isinstance(value, float) or not math.isfinite(value):
            raise _inconsistent(f"{owner}: {name} is not a finite number")


def _assemble(
    grid: GridModel,
    raw: RawSolution,
    options: PowerFlowOptions,
    solver: PowerFlowSolver,
    digest: str,
) -> PowerFlowResult:
    energized = energized_bus_ids(grid)

    buses: list[BusResult] = []
    for bus in grid.buses:
        raw_bus = raw.buses.get(bus.id)
        if bus.id not in energized:
            if raw_bus is not None and math.isfinite(raw_bus.voltage_pu):
                raise _inconsistent(f"bus {bus.id!r} is de-energised but the solver gave a voltage")
            buses.append(
                BusResult(
                    bus_id=bus.id,
                    energized=False,
                    voltage_pu=None,
                    voltage_angle_degree=None,
                    p_mw=None,
                    q_mvar=None,
                )
            )
            continue
        if raw_bus is None:
            raise _inconsistent(f"bus {bus.id!r} is energised but the solver gave no result")
        _require_finite(
            f"bus {bus.id!r}",
            voltage_pu=raw_bus.voltage_pu,
            voltage_angle_degree=raw_bus.voltage_angle_degree,
            p_mw=raw_bus.p_mw,
            q_mvar=raw_bus.q_mvar,
        )
        if raw_bus.voltage_pu <= 0:
            raise _inconsistent(f"bus {bus.id!r}: voltage magnitude is not positive")
        buses.append(
            BusResult(
                bus_id=bus.id,
                energized=True,
                voltage_pu=raw_bus.voltage_pu,
                voltage_angle_degree=raw_bus.voltage_angle_degree,
                p_mw=raw_bus.p_mw,
                q_mvar=raw_bus.q_mvar,
            )
        )

    lines: list[LineResult] = []
    active_losses = reactive_losses = 0.0
    for line in grid.lines:
        live = line.in_service and line.from_bus_id in energized and line.to_bus_id in energized
        if not live:
            lines.append(
                LineResult(
                    line_id=line.id,
                    energized=False,
                    p_from_mw=None,
                    q_from_mvar=None,
                    p_to_mw=None,
                    q_to_mvar=None,
                    active_loss_mw=None,
                    reactive_loss_mvar=None,
                    current_ka=None,
                    loading_percent=None,
                )
            )
            continue
        raw_line = raw.lines.get(line.id)
        if raw_line is None:
            raise _inconsistent(f"line {line.id!r} is energised but the solver gave no result")
        _require_finite(
            f"line {line.id!r}",
            p_from_mw=raw_line.p_from_mw,
            q_from_mvar=raw_line.q_from_mvar,
            p_to_mw=raw_line.p_to_mw,
            q_to_mvar=raw_line.q_to_mvar,
            current_ka=raw_line.current_ka,
            loading_percent=raw_line.loading_percent,
        )
        loss_p = raw_line.p_from_mw + raw_line.p_to_mw
        loss_q = raw_line.q_from_mvar + raw_line.q_to_mvar
        active_losses += loss_p
        reactive_losses += loss_q
        lines.append(
            LineResult(
                line_id=line.id,
                energized=True,
                p_from_mw=raw_line.p_from_mw,
                q_from_mvar=raw_line.q_from_mvar,
                p_to_mw=raw_line.p_to_mw,
                q_to_mvar=raw_line.q_to_mvar,
                active_loss_mw=loss_p,
                reactive_loss_mvar=loss_q,
                current_ka=raw_line.current_ka,
                loading_percent=raw_line.loading_percent,
            )
        )

    sources: list[ExternalGridResult] = []
    supply_p = supply_q = 0.0
    for source in grid.external_grids:
        if not (source.in_service and source.bus_id in energized):
            sources.append(
                ExternalGridResult(
                    external_grid_id=source.id, energized=False, p_mw=None, q_mvar=None
                )
            )
            continue
        raw_source = raw.external_grids.get(source.id)
        if raw_source is None:
            raise _inconsistent(f"external grid {source.id!r} has no result")
        _require_finite(
            f"external grid {source.id!r}", p_mw=raw_source.p_mw, q_mvar=raw_source.q_mvar
        )
        supply_p += raw_source.p_mw
        supply_q += raw_source.q_mvar
        sources.append(
            ExternalGridResult(
                external_grid_id=source.id,
                energized=True,
                p_mw=raw_source.p_mw,
                q_mvar=raw_source.q_mvar,
            )
        )

    served_p = served_q = unserved_p = unserved_q = 0.0
    for load in grid.loads:
        if not load.in_service:
            continue
        if load.bus_id in energized:
            served_p += load.p_mw
            served_q += load.q_mvar
        else:
            unserved_p += load.p_mw
            unserved_q += load.q_mvar

    tolerance = balance_tolerance(options, len(energized))
    residual_p = supply_p - served_p - active_losses
    residual_q = supply_q - served_q - reactive_losses
    if abs(residual_p) > tolerance or abs(residual_q) > tolerance:
        raise _inconsistent(
            f"power balance violated: {residual_p:.3e} MW, {residual_q:.3e} MVAr "
            f"(tolerance {tolerance:.1e})"
        )

    in_service_bus_ids = {bus.id for bus in grid.buses if bus.in_service}
    return PowerFlowResult(
        converged=True,
        failure_code=None,
        grid_hash=digest,
        solver_name=solver.name,
        solver_version=solver.version,
        algorithm=ALGORITHM,
        options=options,
        buses=tuple(buses),
        lines=tuple(lines),
        external_grids=tuple(sources),
        totals=PowerFlowTotals(
            external_supply_mw=supply_p,
            external_supply_mvar=supply_q,
            served_load_mw=served_p,
            served_load_mvar=served_q,
            unserved_load_mw=unserved_p,
            unserved_load_mvar=unserved_q,
            active_losses_mw=active_losses,
            reactive_losses_mvar=reactive_losses,
        ),
        unsupplied_bus_ids=tuple(sorted(in_service_bus_ids - energized)),
    )


def run_power_flow(
    grid: GridModel, solver: PowerFlowSolver, options: PowerFlowOptions | None = None
) -> PowerFlowResult:
    """Solve the balanced, steady-state AC power flow of ``grid``.

    Raises:
        GridValidationError: the grid is not a valid input (nothing was solved).
        SolverExecutionError: the solver crashed, or its solution failed a consistency check.
    """
    options = options or PowerFlowOptions()
    ensure_valid(grid)
    digest = grid_hash(grid)

    try:
        raw = solver.solve(grid, options)
    except GridEngineError:
        raise
    except Exception as error:
        # The type only: a solver's message may quote input data.
        raise SolverExecutionError(
            ErrorCode.SOLVER_FAILED, f"{solver.name} raised {type(error).__name__}"
        ) from error

    if not raw.converged:
        # Whatever the solver left behind is not a solution. Nothing of it is read.
        return PowerFlowResult(
            converged=False,
            failure_code=ErrorCode.POWER_FLOW_NOT_CONVERGED,
            grid_hash=digest,
            solver_name=solver.name,
            solver_version=solver.version,
            algorithm=ALGORITHM,
            options=options,
        )
    return _assemble(grid, raw, options, solver, digest)
