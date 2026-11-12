"""Disconnected and out-of-service elements: reported as absent, never as zero."""

from dataclasses import replace

import pytest
from grid_factories import three_bus_radial, with_bus, with_line

from gridwise_grid_engine import (
    Bus,
    Line,
    Load,
    PowerFlowSolver,
    energized_bus_ids,
    run_power_flow,
)

BALANCE_MW = 1e-6


def test_everything_is_energised_in_the_intact_network(solver: PowerFlowSolver) -> None:
    grid = three_bus_radial()
    assert energized_bus_ids(grid) == {"a", "b", "c"}
    result = run_power_flow(grid, solver)
    assert result.converged
    assert result.unsupplied_bus_ids == ()
    assert all(bus.energized and bus.voltage_pu is not None for bus in result.buses)
    assert result.totals is not None
    assert result.totals.served_load_mw == 3.0
    assert result.totals.unserved_load_mw == 0.0
    assert result.totals.external_supply_mw == pytest.approx(
        result.totals.served_load_mw + result.totals.active_losses_mw, abs=BALANCE_MW
    )
    assert result.totals.external_supply_mvar == pytest.approx(
        result.totals.served_load_mvar + result.totals.reactive_losses_mvar, abs=BALANCE_MW
    )
    # Voltage falls along a loaded radial feeder.
    a, b, c = (bus.voltage_pu for bus in result.buses)
    assert a is not None
    assert b is not None
    assert c is not None
    assert a > b > c


def test_a_line_outage_de_energises_what_is_behind_it(solver: PowerFlowSolver) -> None:
    grid = with_line(three_bus_radial(), "bc", in_service=False)
    assert energized_bus_ids(grid) == {"a", "b"}

    result = run_power_flow(grid, solver)
    assert result.converged
    assert result.unsupplied_bus_ids == ("c",)

    by_id = {bus.bus_id: bus for bus in result.buses}
    assert by_id["b"].energized
    assert by_id["b"].voltage_pu is not None
    dead = by_id["c"]
    assert dead.energized is False
    assert (dead.voltage_pu, dead.voltage_angle_degree, dead.p_mw, dead.q_mvar) == (
        None,
        None,
        None,
        None,
    )

    lines = {line.line_id: line for line in result.lines}
    assert lines["ab"].energized
    assert lines["ab"].loading_percent is not None
    out = lines["bc"]
    assert out.energized is False
    assert out.loading_percent is None
    assert out.current_ka is None
    assert out.active_loss_mw is None

    assert result.totals is not None
    assert result.totals.served_load_mw == 2.0
    assert result.totals.unserved_load_mw == 1.0  # the lost load is reported, not dropped
    assert result.totals.unserved_load_mvar == 0.3
    assert result.totals.external_supply_mw == pytest.approx(
        2.0 + result.totals.active_losses_mw, abs=BALANCE_MW
    )


def test_losing_the_first_line_leaves_only_the_slack_bus(solver: PowerFlowSolver) -> None:
    result = run_power_flow(with_line(three_bus_radial(), "ab", in_service=False), solver)
    assert result.converged
    assert result.unsupplied_bus_ids == ("b", "c")
    assert result.totals is not None
    assert result.totals.served_load_mw == 0.0
    assert result.totals.unserved_load_mw == 3.0
    assert result.totals.external_supply_mw == pytest.approx(0.0, abs=BALANCE_MW)
    assert all(not line.energized for line in result.lines)


def test_an_out_of_service_bus_takes_its_line_and_load_with_it(solver: PowerFlowSolver) -> None:
    grid = with_bus(three_bus_radial(), "c", in_service=False)
    assert energized_bus_ids(grid) == {"a", "b"}
    result = run_power_flow(grid, solver)

    assert result.converged
    # Out of service is a decision, not a fault: it is not listed as unsupplied.
    assert result.unsupplied_bus_ids == ()
    assert result.buses[2].energized is False
    assert result.buses[2].voltage_pu is None
    assert result.lines[1].energized is False
    assert result.totals is not None
    assert result.totals.served_load_mw == 2.0
    assert result.totals.unserved_load_mw == 1.0

    # The line to the dead bus is fully out, not left charging from its live end: the
    # result is identical to switching that line off explicitly.
    line_off = run_power_flow(with_line(grid, "bc", in_service=False), solver)
    assert result.buses[:2] == line_off.buses[:2]
    assert result.lines[0] == line_off.lines[0]
    assert result.totals.external_supply_mvar == line_off.totals.external_supply_mvar  # type: ignore[union-attr]


def test_an_out_of_service_load_is_neither_served_nor_unserved(solver: PowerFlowSolver) -> None:
    grid = three_bus_radial()
    grid = replace(
        grid,
        loads=tuple(
            replace(load, in_service=False) if load.id == "load-c" else load for load in grid.loads
        ),
    )
    result = run_power_flow(grid, solver)
    assert result.totals is not None
    assert result.totals.served_load_mw == 2.0
    assert result.totals.unserved_load_mw == 0.0
    assert all(bus.energized for bus in result.buses)


def test_an_island_with_no_source_is_solved_around(solver: PowerFlowSolver) -> None:
    """Two extra buses joined to each other but to nothing else."""
    grid = three_bus_radial()
    grid = replace(
        grid,
        buses=(
            *grid.buses,
            Bus(id="x", name="X", nominal_voltage_kv=20.0),
            Bus(id="y", name="Y", nominal_voltage_kv=20.0),
        ),
        lines=(
            *grid.lines,
            Line(
                id="xy",
                name="xy",
                from_bus_id="x",
                to_bus_id="y",
                length_km=1.0,
                r_ohm_per_km=0.2,
                x_ohm_per_km=0.1,
                c_nf_per_km=0.0,
                max_i_ka=0.3,
            ),
        ),
        loads=(*grid.loads, Load(id="load-y", name="Load Y", bus_id="y", p_mw=0.7, q_mvar=0.1)),
    )
    intact = run_power_flow(three_bus_radial(), solver)
    result = run_power_flow(grid, solver)

    assert result.converged
    assert result.unsupplied_bus_ids == ("x", "y")
    assert result.totals is not None
    assert result.totals.unserved_load_mw == 0.7
    # The energised part is solved exactly as if the island were not there.
    for bus, reference in zip(result.buses[:3], intact.buses, strict=True):
        assert bus.voltage_pu == pytest.approx(reference.voltage_pu, abs=1e-12)
    assert [line.energized for line in result.lines] == [True, True, False]
