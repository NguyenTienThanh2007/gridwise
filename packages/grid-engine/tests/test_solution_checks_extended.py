"""The engine's checks on a solution, for transformers and generators.

Each test takes a real, correct solution, changes one thing a faulty solver could get
wrong, and requires the engine to reject it instead of returning it. The untouched
solution is accepted, so a rejection is caused by the change alone.
"""

from collections.abc import Callable
from dataclasses import replace

import pytest
from grid_factories import (
    constant_power_generator,
    substation_feeder,
    switch,
    transformer_feeder,
    two_bus,
    voltage_controlled_generator,
)
from test_non_convergence import assert_no_solution

from gridwise_grid_engine import (
    ErrorCode,
    GridModel,
    PowerFlowOptions,
    RawSolution,
    SolverExecutionError,
    run_power_flow,
)
from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver

type Tamper = Callable[[RawSolution], RawSolution]


class TamperingSolver:
    """The real solver, with one deliberate fault applied to what it returns."""

    name = "tampering"
    version = "0"

    def __init__(self, real: PandapowerSolver, tamper: Tamper) -> None:
        self._real = real
        self._tamper = tamper

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        return self._tamper(self._real.solve(grid, options))


def _change(mapping_name: str, key: str, **changes: float) -> Tamper:
    def tamper(raw: RawSolution) -> RawSolution:
        mapping = dict(getattr(raw, mapping_name))
        mapping[key] = replace(mapping[key], **changes)
        return replace(raw, **{mapping_name: mapping})  # type: ignore[arg-type]

    return tamper


def _drop(mapping_name: str, key: str) -> Tamper:
    def tamper(raw: RawSolution) -> RawSolution:
        mapping = dict(getattr(raw, mapping_name))
        del mapping[key]
        return replace(raw, **{mapping_name: mapping})  # type: ignore[arg-type]

    return tamper


def with_unit(generator: object) -> GridModel:
    return replace(two_bus(), generators=(generator,))  # type: ignore[arg-type]


CONTROLLED = with_unit(voltage_controlled_generator("load", 2.0, 1.01))
LIMITED = with_unit(
    voltage_controlled_generator("load", 2.0, 1.01, min_q_mvar=-0.5, max_q_mvar=0.5)
)
EMBEDDED = with_unit(constant_power_generator("load", 2.0, 0.5))


@pytest.mark.parametrize(
    "grid", [transformer_feeder(), substation_feeder(), CONTROLLED, LIMITED, EMBEDDED]
)
def test_untouched_solutions_are_accepted(solver: PandapowerSolver, grid: GridModel) -> None:
    assert run_power_flow(grid, TamperingSolver(solver, lambda raw: raw)).converged


@pytest.mark.parametrize(
    ("grid", "tamper"),
    [
        # A transformer that loses less than it does: the balance no longer closes.
        (transformer_feeder(), _change("transformers", "t1", p_hv_mw=10.0)),
        (transformer_feeder(), _change("transformers", "t1", q_lv_mvar=0.0)),
        (transformer_feeder(), _change("transformers", "t1", loading_percent=float("nan"))),
        (transformer_feeder(), _change("transformers", "t1", current_hv_ka=float("inf"))),
        (transformer_feeder(), _drop("transformers", "t1")),
        # A generator that does not deliver its set-points.
        (EMBEDDED, _change("generators", "unit", p_mw=1.0)),
        (EMBEDDED, _change("generators", "unit", q_mvar=0.0)),
        (EMBEDDED, _change("generators", "unit", p_mw=float("nan"))),
        (EMBEDDED, _drop("generators", "unit")),
        (CONTROLLED, _change("generators", "unit", p_mw=2.5)),
        # A voltage-controlled unit whose bus is not at the set-point, with no limit to
        # explain it.
        (CONTROLLED, _change("buses", "load", voltage_pu=1.0)),
        # With limits: off the set-point but not at a limit either.
        (LIMITED, _change("generators", "unit", q_mvar=0.2)),
    ],
)
def test_a_faulty_solution_is_rejected_not_returned(
    solver: PandapowerSolver, grid: GridModel, tamper: Tamper
) -> None:
    with pytest.raises(SolverExecutionError) as raised:
        run_power_flow(grid, TamperingSolver(solver, tamper))
    assert raised.value.code is ErrorCode.INCONSISTENT_SOLUTION


def test_holding_the_set_point_beyond_a_reactive_limit_is_rejected(
    solver: PandapowerSolver,
) -> None:
    """A solver that ignored the limits would hold 1.01 pu with about 14 MVAr. The engine
    must not accept that for a unit limited to 0.5 MVAr."""

    class IgnoresLimits:
        name = "ignores-limits"
        version = "0"

        def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
            unlimited = replace(
                grid,
                generators=tuple(
                    replace(unit, min_q_mvar=None, max_q_mvar=None) for unit in grid.generators
                ),
            )
            return solver.solve(unlimited, options)

    with pytest.raises(SolverExecutionError) as raised:
        run_power_flow(LIMITED, IgnoresLimits())
    assert raised.value.code is ErrorCode.INCONSISTENT_SOLUTION


def test_a_voltage_on_a_bus_behind_an_open_switch_is_rejected(solver: PandapowerSolver) -> None:
    """A solver that ignored switches would energise what the engine knows to be dead."""

    class IgnoresSwitches:
        name = "ignores-switches"
        version = "0"

        def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
            return solver.solve(replace(grid, switches=()), options)

    grid = replace(substation_feeder(), switches=(switch("s", "b", "line", "bc", closed=False),))
    with pytest.raises(SolverExecutionError) as raised:
        run_power_flow(grid, IgnoresSwitches())
    assert raised.value.code is ErrorCode.INCONSISTENT_SOLUTION


def test_an_overloaded_transformer_feeder_returns_no_values(solver: PandapowerSolver) -> None:
    """Far beyond what a 25 MVA, 12 % transformer can transfer: no operating point."""
    assert_no_solution(run_power_flow(transformer_feeder(p_mw=400.0, q_mvar=150.0), solver))


def test_a_failed_solve_with_generators_returns_no_generator_values(
    solver: PandapowerSolver,
) -> None:
    grid = replace(
        two_bus(p_mw=84.0, q_mvar=31.5), generators=(constant_power_generator("source", 1.0),)
    )
    assert_no_solution(run_power_flow(grid, solver))
