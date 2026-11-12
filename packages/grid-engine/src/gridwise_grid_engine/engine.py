"""run_power_flow: the one entry point for solving a grid.

    validate -> solve -> check the solution -> typed result

The checks after solving are what make the result trustworthy regardless of solver:

* every energised element must have finite values;
* every de-energised element must have none (it gets ``None``, never a number);
* supply (external grids and generators) must equal served load plus losses, for active
  and reactive power;
* a generator must deliver its set-points, and a voltage-controlled one must either hold
  its voltage or sit at a reactive limit.

A solution that fails a check is rejected with ``INCONSISTENT_SOLUTION`` rather than
returned. A power flow that does not converge is an expected outcome, returned as a result
with ``converged=False`` and no values at all.
"""

import math

from gridwise_grid_engine.errors import ErrorCode, GridEngineError, SolverExecutionError
from gridwise_grid_engine.hashing import grid_hash
from gridwise_grid_engine.model import VOLTAGE_CONTROL, Generator, GridModel
from gridwise_grid_engine.results import (
    BusResult,
    ExternalGridResult,
    GeneratorResult,
    LineResult,
    PowerFlowResult,
    PowerFlowTotals,
    TransformerResult,
)
from gridwise_grid_engine.solver import PowerFlowOptions, PowerFlowSolver, RawSolution
from gridwise_grid_engine.topology import analyze_energization
from gridwise_grid_engine.validation import ensure_valid

ALGORITHM = "newton_raphson"

#: Floor of the power-balance check, in MW / MVAr.
BALANCE_TOLERANCE_FLOOR = 1e-6


def balance_tolerance(options: PowerFlowOptions, node_count: int) -> float:
    """Each node may be off by the solver tolerance; allow that to add up, with margin."""
    return max(BALANCE_TOLERANCE_FLOOR, 100 * options.tolerance_mva * node_count)


def _inconsistent(message: str) -> SolverExecutionError:
    return SolverExecutionError(ErrorCode.INCONSISTENT_SOLUTION, message)


def _require_finite(owner: str, **values: float) -> None:
    for name, value in values.items():
        if not isinstance(value, float) or not math.isfinite(value):
            raise _inconsistent(f"{owner}: {name} is not a finite number")


#: How closely a voltage-controlled generator's bus must sit at its set-point to count as
#: holding it, in per unit; and how closely its reactive power must sit at a limit to count
#: as limited, in MVAr.
SETPOINT_TOLERANCE_PU = 1e-6
REACTIVE_LIMIT_TOLERANCE_MVAR = 1e-6


def _bus_results(
    grid: GridModel, raw: RawSolution, energized: frozenset[str]
) -> tuple[list[BusResult], dict[str, float]]:
    results: list[BusResult] = []
    voltages: dict[str, float] = {}
    for bus in grid.buses:
        raw_bus = raw.buses.get(bus.id)
        if bus.id not in energized:
            if raw_bus is not None and math.isfinite(raw_bus.voltage_pu):
                raise _inconsistent(f"bus {bus.id!r} is de-energised but the solver gave a voltage")
            results.append(
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
        voltages[bus.id] = raw_bus.voltage_pu
        results.append(
            BusResult(
                bus_id=bus.id,
                energized=True,
                voltage_pu=raw_bus.voltage_pu,
                voltage_angle_degree=raw_bus.voltage_angle_degree,
                p_mw=raw_bus.p_mw,
                q_mvar=raw_bus.q_mvar,
            )
        )
    return results, voltages


def _line_results(
    grid: GridModel, raw: RawSolution, energized_lines: frozenset[str]
) -> tuple[list[LineResult], float, float]:
    results: list[LineResult] = []
    active_losses = reactive_losses = 0.0
    for line in grid.lines:
        if line.id not in energized_lines:
            results.append(
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
        results.append(
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
    return results, active_losses, reactive_losses


def _transformer_results(
    grid: GridModel, raw: RawSolution, energized_transformers: frozenset[str]
) -> tuple[list[TransformerResult], float, float]:
    results: list[TransformerResult] = []
    active_losses = reactive_losses = 0.0
    for transformer in grid.transformers:
        if transformer.id not in energized_transformers:
            results.append(
                TransformerResult(
                    transformer_id=transformer.id,
                    energized=False,
                    p_hv_mw=None,
                    q_hv_mvar=None,
                    p_lv_mw=None,
                    q_lv_mvar=None,
                    active_loss_mw=None,
                    reactive_loss_mvar=None,
                    current_hv_ka=None,
                    current_lv_ka=None,
                    loading_percent=None,
                )
            )
            continue
        raw_transformer = raw.transformers.get(transformer.id)
        if raw_transformer is None:
            raise _inconsistent(
                f"transformer {transformer.id!r} is energised but the solver gave no result"
            )
        _require_finite(
            f"transformer {transformer.id!r}",
            p_hv_mw=raw_transformer.p_hv_mw,
            q_hv_mvar=raw_transformer.q_hv_mvar,
            p_lv_mw=raw_transformer.p_lv_mw,
            q_lv_mvar=raw_transformer.q_lv_mvar,
            current_hv_ka=raw_transformer.current_hv_ka,
            current_lv_ka=raw_transformer.current_lv_ka,
            loading_percent=raw_transformer.loading_percent,
        )
        loss_p = raw_transformer.p_hv_mw + raw_transformer.p_lv_mw
        loss_q = raw_transformer.q_hv_mvar + raw_transformer.q_lv_mvar
        active_losses += loss_p
        reactive_losses += loss_q
        results.append(
            TransformerResult(
                transformer_id=transformer.id,
                energized=True,
                p_hv_mw=raw_transformer.p_hv_mw,
                q_hv_mvar=raw_transformer.q_hv_mvar,
                p_lv_mw=raw_transformer.p_lv_mw,
                q_lv_mvar=raw_transformer.q_lv_mvar,
                active_loss_mw=loss_p,
                reactive_loss_mvar=loss_q,
                current_hv_ka=raw_transformer.current_hv_ka,
                current_lv_ka=raw_transformer.current_lv_ka,
                loading_percent=raw_transformer.loading_percent,
            )
        )
    return results, active_losses, reactive_losses


def _reactive_limit_reached(generator: Generator, q_mvar: float, bus_voltage_pu: float) -> bool:
    """Decide, and verify, whether a voltage-controlled generator holds its set-point.

    Either its bus is at the set-point (with reactive power inside any limits), or it has
    limits and sits on one of them. Anything else is not a valid solution.
    """
    owner = f"generator {generator.id!r}"
    setpoint = generator.voltage_setpoint_pu
    if setpoint is None:  # excluded by validation
        raise _inconsistent(f"{owner}: no voltage set-point")
    low, high = generator.min_q_mvar, generator.max_q_mvar
    has_limits = low is not None and high is not None

    if abs(bus_voltage_pu - setpoint) <= SETPOINT_TOLERANCE_PU:
        if (
            low is not None
            and high is not None
            and not (
                low - REACTIVE_LIMIT_TOLERANCE_MVAR
                <= q_mvar
                <= high + REACTIVE_LIMIT_TOLERANCE_MVAR
            )
        ):
            raise _inconsistent(f"{owner}: holds its set-point with reactive power beyond a limit")
        return False
    if not has_limits:
        raise _inconsistent(f"{owner}: the bus is not at the voltage set-point")
    at_limit = any(
        limit is not None and abs(q_mvar - limit) <= REACTIVE_LIMIT_TOLERANCE_MVAR
        for limit in (low, high)
    )
    if not at_limit:
        raise _inconsistent(
            f"{owner}: the bus is not at the voltage set-point and the unit is not at a limit"
        )
    return True


def _generator_results(
    grid: GridModel, raw: RawSolution, energized: frozenset[str], voltages: dict[str, float]
) -> tuple[list[GeneratorResult], float, float, float]:
    results: list[GeneratorResult] = []
    supply_p = supply_q = unavailable_p = 0.0
    for generator in grid.generators:
        if not (generator.in_service and generator.bus_id in energized):
            if generator.in_service:
                unavailable_p += generator.p_mw
            results.append(
                GeneratorResult(
                    generator_id=generator.id,
                    energized=False,
                    p_mw=None,
                    q_mvar=None,
                    reactive_limit_reached=None,
                )
            )
            continue
        raw_generator = raw.generators.get(generator.id)
        if raw_generator is None:
            raise _inconsistent(f"generator {generator.id!r} has no result")
        owner = f"generator {generator.id!r}"
        _require_finite(owner, p_mw=raw_generator.p_mw, q_mvar=raw_generator.q_mvar)
        # The active power is an input in both modes; so is the reactive power of a
        # constant-power unit. The solver must hand them back unchanged.
        if abs(raw_generator.p_mw - generator.p_mw) > BALANCE_TOLERANCE_FLOOR:
            raise _inconsistent(f"{owner}: active power differs from its set-point")
        limited: bool | None = None
        if generator.control_mode == VOLTAGE_CONTROL:
            limited = _reactive_limit_reached(
                generator, raw_generator.q_mvar, voltages[generator.bus_id]
            )
        elif abs(raw_generator.q_mvar - (generator.q_mvar or 0.0)) > BALANCE_TOLERANCE_FLOOR:
            raise _inconsistent(f"{owner}: reactive power differs from its set-point")
        supply_p += raw_generator.p_mw
        supply_q += raw_generator.q_mvar
        results.append(
            GeneratorResult(
                generator_id=generator.id,
                energized=True,
                p_mw=raw_generator.p_mw,
                q_mvar=raw_generator.q_mvar,
                reactive_limit_reached=limited,
            )
        )
    return results, supply_p, supply_q, unavailable_p


def _external_grid_results(
    grid: GridModel, raw: RawSolution, energized: frozenset[str]
) -> tuple[list[ExternalGridResult], float, float]:
    results: list[ExternalGridResult] = []
    supply_p = supply_q = 0.0
    for source in grid.external_grids:
        if not (source.in_service and source.bus_id in energized):
            results.append(
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
        results.append(
            ExternalGridResult(
                external_grid_id=source.id,
                energized=True,
                p_mw=raw_source.p_mw,
                q_mvar=raw_source.q_mvar,
            )
        )
    return results, supply_p, supply_q


def _assemble(
    grid: GridModel,
    raw: RawSolution,
    options: PowerFlowOptions,
    solver: PowerFlowSolver,
    digest: str,
) -> PowerFlowResult:
    energization = analyze_energization(grid)
    energized = energization.bus_ids

    buses, voltages = _bus_results(grid, raw, energized)
    lines, line_loss_p, line_loss_q = _line_results(grid, raw, energization.line_ids)
    transformers, transformer_loss_p, transformer_loss_q = _transformer_results(
        grid, raw, energization.transformer_ids
    )
    generators, generation_p, generation_q, unavailable_p = _generator_results(
        grid, raw, energized, voltages
    )
    sources, external_p, external_q = _external_grid_results(grid, raw, energized)

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

    active_losses = line_loss_p + transformer_loss_p
    reactive_losses = line_loss_q + transformer_loss_q
    # Every energised node may be off by the solver tolerance. Branches count too: an
    # open-ended line or transformer has an internal node of its own.
    node_count = len(energized) + len(energization.line_ids) + len(energization.transformer_ids)
    tolerance = balance_tolerance(options, node_count)
    residual_p = external_p + generation_p - served_p - active_losses
    residual_q = external_q + generation_q - served_q - reactive_losses
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
        transformers=tuple(transformers),
        generators=tuple(generators),
        external_grids=tuple(sources),
        totals=PowerFlowTotals(
            external_supply_mw=external_p,
            external_supply_mvar=external_q,
            generation_mw=generation_p,
            generation_mvar=generation_q,
            unavailable_generation_mw=unavailable_p,
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
