"""Switches: what an open or closed switch does to energisation and to the results.

The references here are equivalences that need no solver knowledge: a network with a
switch in some position must behave exactly like a simpler network without that switch.
"""

from dataclasses import replace

import pytest
from grid_factories import substation_feeder, switch, three_bus_radial, two_bus, with_line

from gridwise_grid_engine import (
    Bus,
    GridModel,
    Load,
    PowerFlowSolver,
    analyze_energization,
    grid_hash,
    run_power_flow,
)

EXACT = 1e-12
SOLVER_TOLERANCE_MVA = 1e-8


def with_switches(grid: GridModel, *switches: object) -> GridModel:
    return replace(grid, switches=switches)  # type: ignore[arg-type]


def without_loads_on(grid: GridModel, bus_id: str) -> GridModel:
    return replace(grid, loads=tuple(load for load in grid.loads if load.bus_id != bus_id))


def test_closed_switches_change_nothing(solver: PowerFlowSolver) -> None:
    plain = run_power_flow(three_bus_radial(), solver)
    switched = run_power_flow(
        with_switches(
            three_bus_radial(),
            switch("s1", "a", "line", "ab"),
            switch("s2", "b", "line", "ab"),
            switch("s3", "c", "line", "bc"),
        ),
        solver,
    )
    assert switched.buses == plain.buses
    assert switched.lines == plain.lines
    assert switched.totals == plain.totals


def test_a_line_open_at_its_far_end_stays_energised_and_draws_charging_current(
    solver: PowerFlowSolver,
) -> None:
    """b --bc-- | c, open at c. The line must behave exactly like a line to an unloaded
    bus: energised from b, carrying only its charging current. Bus c is dead."""
    opened = run_power_flow(
        with_switches(three_bus_radial(), switch("s", "c", "line", "bc", closed=False)), solver
    )
    reference = run_power_flow(without_loads_on(three_bus_radial(), "c"), solver)

    assert opened.converged
    line = {item.line_id: item for item in opened.lines}["bc"]
    expected = {item.line_id: item for item in reference.lines}["bc"]
    assert line.energized is True
    assert line.p_from_mw == pytest.approx(expected.p_from_mw, abs=EXACT)
    assert line.q_from_mvar == pytest.approx(expected.q_from_mvar, abs=EXACT)
    assert line.q_from_mvar is not None
    assert line.q_from_mvar < 0  # capacitive: the line supplies reactive power
    assert line.p_to_mw == pytest.approx(0.0, abs=EXACT)
    assert line.q_to_mvar == pytest.approx(0.0, abs=EXACT)
    assert line.current_ka == pytest.approx(expected.current_ka, abs=EXACT)

    # Upstream of the open point the two networks are the same network.
    for bus_id in ("a", "b"):
        got = {bus.bus_id: bus for bus in opened.buses}[bus_id]
        want = {bus.bus_id: bus for bus in reference.buses}[bus_id]
        assert got.voltage_pu == pytest.approx(want.voltage_pu, abs=EXACT)

    dead = {bus.bus_id: bus for bus in opened.buses}["c"]
    assert dead.energized is False
    assert dead.voltage_pu is None
    assert dead.p_mw is None
    assert opened.unsupplied_bus_ids == ("c",)
    assert opened.totals is not None
    assert opened.totals.unserved_load_mw == pytest.approx(1.0)


def test_a_line_open_at_its_supply_end_is_dead_like_a_line_out_of_service(
    solver: PowerFlowSolver,
) -> None:
    opened = run_power_flow(
        with_switches(three_bus_radial(), switch("s", "b", "line", "bc", closed=False)), solver
    )
    reference = run_power_flow(with_line(three_bus_radial(), "bc", in_service=False), solver)

    assert opened.buses == reference.buses
    assert opened.lines == reference.lines
    assert opened.totals == reference.totals
    line = {item.line_id: item for item in opened.lines}["bc"]
    assert line.energized is False
    assert line.p_from_mw is None
    assert line.current_ka is None


def test_a_line_open_at_both_ends_is_dead(solver: PowerFlowSolver) -> None:
    result = run_power_flow(
        with_switches(
            three_bus_radial(),
            switch("s1", "b", "line", "bc", closed=False),
            switch("s2", "c", "line", "bc", closed=False),
        ),
        solver,
    )
    line = {item.line_id: item for item in result.lines}["bc"]
    assert line.energized is False
    assert line.loading_percent is None
    assert result.unsupplied_bus_ids == ("c",)


def test_a_normally_open_point_in_a_ring(solver: PowerFlowSolver) -> None:
    """a-b-c plus a tie line c-a that is open at c: both of its buses are live, the tie
    carries charging current only, and the rest is the radial network plus that charging."""
    radial = three_bus_radial()
    tie = replace(radial.lines[0], id="ca", name="ca", from_bus_id="c", to_bus_id="a")
    ring = replace(radial, lines=(*radial.lines, tie))
    result = run_power_flow(
        with_switches(ring, switch("nop", "c", "line", "ca", closed=False)), solver
    )

    assert result.converged
    assert result.unsupplied_bus_ids == ()
    line = {item.line_id: item for item in result.lines}["ca"]
    assert line.energized is True
    # The open end, at c: zero to within the solver's own mismatch tolerance (1e-8 MVA).
    assert line.p_from_mw == pytest.approx(0.0, abs=SOLVER_TOLERANCE_MVA)
    assert line.q_from_mvar == pytest.approx(0.0, abs=SOLVER_TOLERANCE_MVA)
    assert line.q_to_mvar is not None
    assert line.q_to_mvar < 0

    closed = run_power_flow(with_switches(ring, switch("nop", "c", "line", "ca")), solver)
    closed_tie = {item.line_id: item for item in closed.lines}["ca"]
    assert closed_tie.p_from_mw is not None
    assert abs(closed_tie.p_from_mw) > 0.1  # closing the ring makes it carry load


def test_a_transformer_open_on_its_low_voltage_side_draws_only_no_load_power(
    solver: PowerFlowSolver,
) -> None:
    opened = run_power_flow(
        with_switches(substation_feeder(), switch("cb", "a", "transformer", "t1", closed=False)),
        solver,
    )
    assert opened.converged
    (transformer,) = opened.transformers
    assert transformer.energized is True
    assert transformer.p_hv_mw == pytest.approx(0.014, rel=1e-3)  # iron losses
    assert transformer.q_hv_mvar == pytest.approx(0.0105, rel=1e-3)
    assert transformer.p_lv_mw == pytest.approx(0.0, abs=EXACT)
    assert transformer.current_lv_ka == pytest.approx(0.0, abs=EXACT)
    assert opened.unsupplied_bus_ids == ("a", "b", "c")
    assert all(line.energized is False and line.p_from_mw is None for line in opened.lines)
    assert opened.totals is not None
    assert opened.totals.unserved_load_mw == pytest.approx(3.0)
    assert opened.totals.active_losses_mw == pytest.approx(transformer.active_loss_mw)


def test_a_transformer_open_on_its_supply_side_is_dead(solver: PowerFlowSolver) -> None:
    result = run_power_flow(
        with_switches(substation_feeder(), switch("cb", "hv", "transformer", "t1", closed=False)),
        solver,
    )
    (transformer,) = result.transformers
    assert transformer.energized is False
    assert transformer.p_hv_mw is None
    assert transformer.loading_percent is None
    (slack,) = result.external_grids
    assert slack.p_mw == pytest.approx(0.0, abs=1e-9)
    assert result.unsupplied_bus_ids == ("a", "b", "c")


def bus_coupler(*, closed: bool) -> GridModel:
    """The radial network with a second busbar ``d`` (its own load) coupled to ``c``."""
    radial = three_bus_radial()
    return replace(
        radial,
        buses=(*radial.buses, Bus(id="d", name="D", nominal_voltage_kv=20.0)),
        loads=(*radial.loads, Load(id="load-d", name="Load D", bus_id="d", p_mw=0.5, q_mvar=0.1)),
        switches=(switch("coupler", "c", "bus", "d", closed=closed),),
    )


def test_a_closed_bus_coupler_makes_two_buses_one_node(solver: PowerFlowSolver) -> None:
    """Equivalent to moving the load of ``d`` onto ``c``."""
    coupled = run_power_flow(bus_coupler(closed=True), solver)
    radial = three_bus_radial()
    reference = run_power_flow(
        replace(
            radial,
            loads=(*radial.loads, Load(id="extra", name="Extra", bus_id="c", p_mw=0.5, q_mvar=0.1)),
        ),
        solver,
    )
    voltage = {bus.bus_id: bus for bus in coupled.buses}
    expected = {bus.bus_id: bus for bus in reference.buses}

    assert voltage["d"].energized is True
    assert voltage["d"].voltage_pu == voltage["c"].voltage_pu
    assert voltage["d"].voltage_angle_degree == voltage["c"].voltage_angle_degree
    assert voltage["c"].voltage_pu == pytest.approx(expected["c"].voltage_pu, abs=EXACT)
    assert coupled.totals is not None
    assert coupled.totals.served_load_mw == pytest.approx(3.5)


def test_an_open_bus_coupler_leaves_the_far_bus_dead(solver: PowerFlowSolver) -> None:
    result = run_power_flow(bus_coupler(closed=False), solver)
    plain = run_power_flow(three_bus_radial(), solver)

    dead = {bus.bus_id: bus for bus in result.buses}["d"]
    assert dead.energized is False
    assert dead.voltage_pu is None
    assert result.buses[:3] == plain.buses
    assert result.unsupplied_bus_ids == ("d",)
    assert result.totals is not None
    assert result.totals.unserved_load_mw == pytest.approx(0.5)


def test_a_switch_at_an_out_of_service_bus_does_not_revive_the_line() -> None:
    """Rule 1 comes first: an out-of-service bus takes its lines with it, whatever the
    switches say."""
    radial = three_bus_radial()
    grid = with_switches(
        replace(
            radial,
            buses=tuple(replace(bus, in_service=bus.id != "c") for bus in radial.buses),
        ),
        switch("s", "c", "line", "bc", closed=False),
    )
    energization = analyze_energization(grid)
    assert energization.bus_ids == {"a", "b"}
    assert energization.line_ids == {"ab"}


def test_energisation_analysis_reports_open_ended_elements() -> None:
    grid = with_switches(substation_feeder(), switch("s", "c", "line", "bc", closed=False))
    energization = analyze_energization(grid)
    assert energization.bus_ids == {"hv", "a", "b"}
    assert energization.line_ids == {"ab", "bc"}
    assert energization.transformer_ids == {"t1"}


def test_a_switch_position_is_part_of_the_grid_identity() -> None:
    closed = with_switches(two_bus(), switch("s", "load", "line", "line"))
    opened = with_switches(two_bus(), switch("s", "load", "line", "line", closed=False))
    assert grid_hash(closed) != grid_hash(opened)
    assert grid_hash(closed) != grid_hash(two_bus())
