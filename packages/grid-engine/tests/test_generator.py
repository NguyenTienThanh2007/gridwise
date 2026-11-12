"""Generators against closed-form two-bus solutions.

Network: slack bus 1 (voltage V1), one line R + jX, bus 2 with a load and a generator.

Constant power: the generator simply reduces the net demand at bus 2, so the closed form of
test_two_bus_analytic.py applies with P = P_load - P_gen and Q = Q_load - Q_gen.

Voltage control: |V2| is given instead of Q. With Z = |Z| at angle beta and delta the angle
by which bus 2 lags bus 1, the power arriving at bus 2 over the line is (line-to-line kV,
ohm, MW):

    P_r = V1 V2 / |Z| * cos(beta - delta) - V2^2 / |Z| * cos(beta)
    Q_r = V1 V2 / |Z| * sin(beta - delta) - V2^2 / |Z| * sin(beta)

P_r = P_load - P_gen is known, which gives delta; Q_r then gives the reactive power the
generator must supply: Q_gen = Q_load - Q_r.
"""

import math
from dataclasses import replace

import pytest
from grid_factories import (
    constant_power_generator,
    three_bus_radial,
    two_bus,
    voltage_controlled_generator,
    with_line,
)
from test_two_bus_analytic import (
    ANGLE_TOLERANCE_DEGREE,
    POWER_TOLERANCE_MW,
    VOLTAGE_TOLERANCE_PU,
    closed_form,
)

from gridwise_grid_engine import GridModel, PowerFlowSolver, run_power_flow

R_OHM, X_OHM = 1.0, 0.5  # two_bus(): 5 km of 0.2 + j0.1 ohm/km
LOAD_P, LOAD_Q = 4.0, 1.5


def with_generator(grid: GridModel, generator: object) -> GridModel:
    return replace(grid, generators=(generator,))  # type: ignore[arg-type]


def voltage_controlled_closed_form(
    v1_kv: float, v2_kv: float, p_received_mw: float
) -> tuple[float, float]:
    """(angle of bus 2 in degrees, reactive power arriving at bus 2 in MVAr)."""
    z = math.hypot(R_OHM, X_OHM)
    beta = math.atan2(X_OHM, R_OHM)
    delta = beta - math.acos((p_received_mw * z + v2_kv**2 * math.cos(beta)) / (v1_kv * v2_kv))
    q_received = v1_kv * v2_kv / z * math.sin(beta - delta) - v2_kv**2 / z * math.sin(beta)
    return -math.degrees(delta), q_received


@pytest.mark.parametrize(
    ("p_gen", "q_gen"),
    [(1.0, 0.0), (2.5, 0.5), (4.0, 1.5), (6.0, -1.0)],  # the last two: no net demand, export
)
def test_a_constant_power_generator_reduces_the_net_demand(
    solver: PowerFlowSolver, p_gen: float, q_gen: float
) -> None:
    grid = with_generator(two_bus(), constant_power_generator("load", p_gen, q_gen))
    expected = closed_form(20.0, R_OHM, X_OHM, LOAD_P - p_gen, LOAD_Q - q_gen)

    result = run_power_flow(grid, solver)
    assert result.converged
    _, bus = result.buses
    (unit,) = result.generators
    (slack,) = result.external_grids
    assert result.totals is not None

    assert bus.voltage_pu == pytest.approx(expected.voltage_pu, abs=VOLTAGE_TOLERANCE_PU)
    assert bus.voltage_angle_degree == pytest.approx(
        expected.angle_degree, abs=ANGLE_TOLERANCE_DEGREE
    )
    assert unit.energized is True
    assert unit.p_mw == pytest.approx(p_gen, abs=POWER_TOLERANCE_MW)
    assert unit.q_mvar == pytest.approx(q_gen, abs=POWER_TOLERANCE_MW)
    assert unit.reactive_limit_reached is None
    assert bus.p_mw == pytest.approx(LOAD_P - p_gen, abs=POWER_TOLERANCE_MW)
    assert slack.p_mw == pytest.approx(LOAD_P - p_gen + expected.loss_mw, abs=POWER_TOLERANCE_MW)
    assert result.totals.generation_mw == pytest.approx(p_gen)
    assert result.totals.served_load_mw == pytest.approx(LOAD_P)


@pytest.mark.parametrize(
    ("p_gen", "setpoint_pu", "slack_pu"),
    [(2.0, 1.01, 1.0), (0.0, 1.0, 1.0), (4.0, 0.99, 1.0), (3.0, 1.02, 1.03), (6.0, 1.0, 1.0)],
)
def test_a_voltage_controlled_generator_holds_its_set_point(
    solver: PowerFlowSolver, p_gen: float, setpoint_pu: float, slack_pu: float
) -> None:
    grid = with_generator(
        two_bus(slack_voltage_pu=slack_pu),
        voltage_controlled_generator("load", p_gen, setpoint_pu),
    )
    angle, q_received = voltage_controlled_closed_form(
        slack_pu * 20.0, setpoint_pu * 20.0, LOAD_P - p_gen
    )

    result = run_power_flow(grid, solver)
    assert result.converged
    _, bus = result.buses
    (unit,) = result.generators

    assert bus.voltage_pu == pytest.approx(setpoint_pu, abs=VOLTAGE_TOLERANCE_PU)
    assert bus.voltage_angle_degree == pytest.approx(angle, abs=ANGLE_TOLERANCE_DEGREE)
    assert unit.p_mw == pytest.approx(p_gen, abs=POWER_TOLERANCE_MW)
    assert unit.q_mvar == pytest.approx(LOAD_Q - q_received, abs=1e-7)
    assert unit.reactive_limit_reached is False


def test_wide_reactive_limits_change_nothing(solver: PowerFlowSolver) -> None:
    free = run_power_flow(
        with_generator(two_bus(), voltage_controlled_generator("load", 2.0, 1.01)), solver
    )
    limited = run_power_flow(
        with_generator(
            two_bus(),
            voltage_controlled_generator("load", 2.0, 1.01, min_q_mvar=-50.0, max_q_mvar=50.0),
        ),
        solver,
    )
    # Not bit-identical: with limits the solver runs its limit check, a different code path.
    for with_limits, without in zip(limited.buses, free.buses, strict=True):
        assert with_limits.voltage_pu == pytest.approx(without.voltage_pu, abs=VOLTAGE_TOLERANCE_PU)
        assert with_limits.q_mvar == pytest.approx(without.q_mvar, abs=1e-6)
    assert limited.generators[0].reactive_limit_reached is False


@pytest.mark.parametrize(
    ("setpoint_pu", "low", "high", "expected_q"),
    [
        (1.01, -0.5, 0.5, 0.5),  # holding 1.01 pu needs about 14 MVAr: capped at +0.5
        (0.95, -0.5, 0.5, -0.5),  # holding 0.95 pu needs absorption: capped at -0.5
    ],
)
def test_at_a_reactive_limit_the_unit_no_longer_holds_its_voltage(
    solver: PowerFlowSolver, setpoint_pu: float, low: float, high: float, expected_q: float
) -> None:
    """At the limit the unit is a constant-power source, so the first closed form applies."""
    p_gen = 2.0
    grid = with_generator(
        two_bus(),
        voltage_controlled_generator("load", p_gen, setpoint_pu, min_q_mvar=low, max_q_mvar=high),
    )
    expected = closed_form(20.0, R_OHM, X_OHM, LOAD_P - p_gen, LOAD_Q - expected_q)

    result = run_power_flow(grid, solver)
    assert result.converged
    _, bus = result.buses
    (unit,) = result.generators

    assert unit.reactive_limit_reached is True
    assert unit.q_mvar == pytest.approx(expected_q, abs=1e-7)
    assert bus.voltage_pu == pytest.approx(expected.voltage_pu, abs=VOLTAGE_TOLERANCE_PU)
    assert bus.voltage_pu != pytest.approx(setpoint_pu, abs=1e-4)


def test_one_limited_and_one_unlimited_unit_in_the_same_network(solver: PowerFlowSolver) -> None:
    grid = three_bus_radial()
    limited = replace(
        voltage_controlled_generator("b", 1.0, 1.03, min_q_mvar=-0.2, max_q_mvar=0.2), id="limited"
    )
    free = replace(voltage_controlled_generator("c", 0.5, 1.0), id="free")
    result = run_power_flow(replace(grid, generators=(limited, free)), solver)

    assert result.converged
    by_id = {unit.generator_id: unit for unit in result.generators}
    voltage = {bus.bus_id: bus.voltage_pu for bus in result.buses}
    assert by_id["limited"].reactive_limit_reached is True
    assert by_id["limited"].q_mvar == pytest.approx(0.2, abs=1e-7)
    assert by_id["free"].reactive_limit_reached is False
    assert voltage["c"] == pytest.approx(1.0, abs=VOLTAGE_TOLERANCE_PU)


def test_a_generator_does_not_energise_an_island(solver: PowerFlowSolver) -> None:
    """Behind an open line, generation and load are both lost. Nothing is made up."""
    grid = with_line(three_bus_radial(), "bc", in_service=False)
    grid = replace(
        grid,
        generators=(
            replace(constant_power_generator("c", 5.0), id="embedded"),
            replace(voltage_controlled_generator("c", 2.0, 1.0), id="controlled", bus_id="c"),
        ),
    )
    # Two units on one bus: only one may control voltage, and here only one does.
    result = run_power_flow(grid, solver)

    assert result.converged
    assert result.unsupplied_bus_ids == ("c",)
    for unit in result.generators:
        assert unit.energized is False
        assert unit.p_mw is None
        assert unit.q_mvar is None
        assert unit.reactive_limit_reached is None
    assert result.totals is not None
    assert result.totals.generation_mw == 0.0
    assert result.totals.unavailable_generation_mw == pytest.approx(7.0)
    assert result.totals.unserved_load_mw == pytest.approx(1.0)


def test_an_out_of_service_generator_is_neither_generation_nor_unavailable(
    solver: PowerFlowSolver,
) -> None:
    unit = replace(constant_power_generator("load", 2.0), in_service=False)
    result = run_power_flow(with_generator(two_bus(), unit), solver)
    plain = run_power_flow(two_bus(), solver)

    assert result.buses == plain.buses
    assert result.generators[0].energized is False
    assert result.generators[0].p_mw is None
    assert result.totals is not None
    assert result.totals.generation_mw == 0.0
    assert result.totals.unavailable_generation_mw == 0.0
