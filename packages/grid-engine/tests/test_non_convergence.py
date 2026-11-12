"""A power flow with no solution must yield no numbers at all.

The infeasible case is not a guess: for a two-bus network the operating point exists only
while the discriminant of the voltage quadratic is non-negative (see
test_two_bus_analytic.py). Beyond that the load exceeds what the line can transfer and the
power flow equations have no real solution, so a correct solver cannot converge.
"""

import dataclasses
import math

import pytest
from grid_factories import three_bus_radial, two_bus

from gridwise_grid_engine import (
    ErrorCode,
    GridModel,
    PowerFlowOptions,
    PowerFlowResult,
    RawSolution,
    SolverExecutionError,
    result_hash,
    run_power_flow,
)
from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
from gridwise_grid_engine.solver import RawBus, RawExternalGrid, RawLine

INFEASIBLE_P_MW = 84.0
INFEASIBLE_Q_MVAR = 31.5


def _discriminant(v1_kv: float, r: float, x: float, p: float, q: float) -> float:
    a = v1_kv**2 - 2 * (p * r + q * x)
    return a**2 - 4 * (p**2 + q**2) * (r**2 + x**2)


def infeasible() -> GridModel:
    return two_bus(p_mw=INFEASIBLE_P_MW, q_mvar=INFEASIBLE_Q_MVAR)


def contains_number(value: object) -> bool:
    """True if any float or int is reachable inside a result's element data."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return False
    if isinstance(value, (int, float)):
        return True
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return any(contains_number(getattr(value, f.name)) for f in dataclasses.fields(value))
    if isinstance(value, (tuple, list)):
        return any(contains_number(item) for item in value)
    return False


def assert_no_solution(result: PowerFlowResult) -> None:
    assert result.converged is False
    assert result.failure_code is ErrorCode.POWER_FLOW_NOT_CONVERGED
    assert result.buses == ()
    assert result.lines == ()
    assert result.transformers == ()
    assert result.generators == ()
    assert result.external_grids == ()
    assert result.totals is None
    assert result.unsupplied_bus_ids == ()
    for part in (
        result.buses,
        result.lines,
        result.transformers,
        result.generators,
        result.external_grids,
        result.totals,
    ):
        assert not contains_number(part)


def test_the_infeasible_case_really_has_no_solution() -> None:
    assert _discriminant(20.0, 1.0, 0.5, 4.0, 1.5) > 0  # the reference case is feasible
    assert _discriminant(20.0, 1.0, 0.5, INFEASIBLE_P_MW, INFEASIBLE_Q_MVAR) < 0


def test_non_convergence_is_reported_with_no_values(solver: PandapowerSolver) -> None:
    result = run_power_flow(infeasible(), solver)
    assert_no_solution(result)
    # Still fully identified, so a failed run can be stored and reproduced.
    assert result.solver_name == "pandapower"
    assert result.algorithm == "newton_raphson"
    assert len(result.grid_hash) == 64


def test_a_failed_solve_does_not_return_the_previous_solution(solver: PandapowerSolver) -> None:
    """Same solver instance: good, bad, good. The bad one must not inherit anything."""
    good_before = run_power_flow(two_bus(), solver)
    assert good_before.converged
    assert contains_number(good_before.buses)

    failed = run_power_flow(infeasible(), solver)
    assert_no_solution(failed)

    good_after = run_power_flow(two_bus(), solver)
    assert good_after == good_before  # and the failure left nothing behind either


def test_a_failed_solve_right_after_a_different_grid(solver: PandapowerSolver) -> None:
    run_power_flow(three_bus_radial(), solver)
    assert_no_solution(run_power_flow(infeasible(), solver))


def test_running_out_of_iterations_is_also_non_convergence(solver: PandapowerSolver) -> None:
    feasible = two_bus(p_mw=40.0, q_mvar=15.0)
    assert run_power_flow(feasible, solver).converged
    assert_no_solution(run_power_flow(feasible, solver, PowerFlowOptions(max_iterations=1)))


def test_failed_results_are_deterministic_and_distinct(solver: PandapowerSolver) -> None:
    first, second = run_power_flow(infeasible(), solver), run_power_flow(infeasible(), solver)
    assert result_hash(first) == result_hash(second)
    assert result_hash(first) != result_hash(run_power_flow(two_bus(), solver))


# --- the engine does not trust a solver ------------------------------------------------


def _plausible_two_bus_solution(**overrides: object) -> RawSolution:
    values: dict[str, object] = {
        "converged": True,
        "buses": {
            "source": RawBus(voltage_pu=1.0, voltage_angle_degree=0.0, p_mw=-4.05, q_mvar=-1.52),
            "load": RawBus(voltage_pu=0.988, voltage_angle_degree=-0.07, p_mw=4.0, q_mvar=1.5),
        },
        "lines": {
            "line": RawLine(
                p_from_mw=4.05,
                q_from_mvar=1.52,
                p_to_mw=-4.0,
                q_to_mvar=-1.5,
                current_ka=0.125,
                loading_percent=41.6,
            )
        },
        "external_grids": {"slack": RawExternalGrid(p_mw=4.05, q_mvar=1.52)},
    }
    values.update(overrides)
    return RawSolution(**values)  # type: ignore[arg-type]


class StubSolver:
    name = "stub"
    version = "0"

    def __init__(self, solution: RawSolution | Exception) -> None:
        self._solution = solution

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        if isinstance(self._solution, Exception):
            raise self._solution
        return self._solution


def test_a_consistent_stub_solution_is_accepted() -> None:
    assert run_power_flow(two_bus(), StubSolver(_plausible_two_bus_solution())).converged


def test_values_left_behind_by_a_solver_that_did_not_converge_are_ignored() -> None:
    stale = dataclasses.replace(_plausible_two_bus_solution(), converged=False)
    assert_no_solution(run_power_flow(two_bus(), StubSolver(stale)))


@pytest.mark.parametrize(
    "solution",
    [
        _plausible_two_bus_solution(buses={}),
        _plausible_two_bus_solution(lines={}),
        _plausible_two_bus_solution(external_grids={}),
        _plausible_two_bus_solution(
            buses={
                "source": RawBus(
                    voltage_pu=1.0, voltage_angle_degree=0.0, p_mw=-4.05, q_mvar=-1.52
                ),
                "load": RawBus(voltage_pu=math.nan, voltage_angle_degree=0.0, p_mw=4.0, q_mvar=1.5),
            }
        ),
        _plausible_two_bus_solution(
            buses={
                "source": RawBus(
                    voltage_pu=1.0, voltage_angle_degree=0.0, p_mw=-4.05, q_mvar=-1.52
                ),
                "load": RawBus(voltage_pu=-0.9, voltage_angle_degree=0.0, p_mw=4.0, q_mvar=1.5),
            }
        ),
        # Violates conservation of energy: 5 MW supplied, 4 MW served, 0.05 MW lost.
        _plausible_two_bus_solution(
            external_grids={"slack": RawExternalGrid(p_mw=5.0, q_mvar=1.52)}
        ),
    ],
    ids=["no-bus", "no-line", "no-source", "nan-voltage", "negative-voltage", "unbalanced"],
)
def test_an_impossible_solution_is_rejected_not_returned(solution: RawSolution) -> None:
    with pytest.raises(SolverExecutionError) as raised:
        run_power_flow(two_bus(), StubSolver(solution))
    assert raised.value.code is ErrorCode.INCONSISTENT_SOLUTION


def test_a_solver_crash_is_reported_without_its_message() -> None:
    crash = RuntimeError("matrix is singular near bus load with p=4.0")
    with pytest.raises(SolverExecutionError) as raised:
        run_power_flow(two_bus(), StubSolver(crash))
    assert raised.value.code is ErrorCode.SOLVER_FAILED
    assert "RuntimeError" in str(raised.value)
    assert "singular" not in str(raised.value)
    assert raised.value.__cause__ is crash
