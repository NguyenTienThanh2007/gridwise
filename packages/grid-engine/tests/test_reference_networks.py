"""Multi-bus networks: published benchmarks through the GRIDWISE model.

Three kinds of evidence, in decreasing independence:

1. ``case9`` (nine buses, three sources, meshed): the engine's voltages are put back into
   the power flow equations, written out here in plain complex arithmetic from the line
   model in docs/domain/grid-engine.md. The power arriving at every bus must equal what
   the loads and sources there exchange. This uses no solver and no matrix library.
2. The CIGRE MV benchmark as shipped in ``reference_grids.cigre_mv`` must equal, element by
   element, the copy pandapower distributes.
3. Both networks, solved through the GRIDWISE model and adapter, must give the same numbers
   as pandapower solving its own copy. This proves the mapping between the two models (ids,
   units, signs, switch and transformer handling), not the solver, which is the same on
   both sides.
"""

import cmath
import math
import warnings
from typing import Any

import pandapower.networks as pn
import pytest
from pandapower_reference import (
    bus_coordinates,
    grid_model_from_pandapower,
    solve_with_pandapower,
)

from gridwise_grid_engine import (
    GridModel,
    PowerFlowResult,
    PowerFlowSolver,
    analyze_energization,
    run_power_flow,
    validate_grid,
)
from gridwise_grid_engine.reference_grids import cigre_mv

MAPPING_TOLERANCE = 1e-9


def _pandapower_cigre() -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pn.create_cigre_network_mv(with_der="pv_wind")


# --- 1. case9: the solution satisfies the power flow equations ----------------------------


def injected_power_mva(grid: GridModel, result: PowerFlowResult) -> dict[str, complex]:
    """Power flowing from each bus into the lines connected to it, from the bus voltages.

    Per line (nominal pi-equivalent, see docs/domain/grid-engine.md):
        Z = (r + jx) * length                     ohm
        Y = j * 2 pi f * c * 1e-9 * length        siemens, half at each end
    With line-to-line voltages in kV, ``V * conj(I * sqrt(3))`` is three-phase power in MVA.
    """
    assert not grid.transformers
    assert not grid.switches
    volts = {
        bus.id: cmath.rect(
            result_bus.voltage_pu * bus.nominal_voltage_kv,  # type: ignore[operator]
            math.radians(result_bus.voltage_angle_degree),  # type: ignore[arg-type]
        )
        for bus, result_bus in zip(grid.buses, result.buses, strict=True)
    }
    power = dict.fromkeys(volts, 0j)
    omega = 2 * math.pi * grid.frequency_hz
    for line in grid.lines:
        series = complex(line.r_ohm_per_km, line.x_ohm_per_km) * line.length_km
        half_shunt = 1j * omega * line.c_nf_per_km * 1e-9 * line.length_km / 2
        v_from, v_to = volts[line.from_bus_id], volts[line.to_bus_id]
        power[line.from_bus_id] += (
            v_from * ((v_from - v_to) / series + v_from * half_shunt).conjugate()
        )
        power[line.to_bus_id] += v_to * ((v_to - v_from) / series + v_to * half_shunt).conjugate()
    return power


def test_case9_is_a_valid_grid_with_voltage_controlled_generators() -> None:
    grid = grid_model_from_pandapower(pn.case9(), name="case9")
    assert validate_grid(grid) == ()
    assert len(grid.buses) == 9
    assert len(grid.lines) == 9
    assert [unit.control_mode for unit in grid.generators] == ["voltage_control"] * 2
    assert grid.frequency_hz == 60.0


def test_case9_solution_satisfies_the_power_flow_equations(solver: PowerFlowSolver) -> None:
    grid = grid_model_from_pandapower(pn.case9(), name="case9")
    result = run_power_flow(grid, solver)
    assert result.converged

    # What each bus hands to the network, from the inputs and the reported source outputs.
    specified = dict.fromkeys((bus.id for bus in grid.buses), 0j)
    for load in grid.loads:
        specified[load.bus_id] -= complex(load.p_mw, load.q_mvar)
    for unit, unit_result in zip(grid.generators, result.generators, strict=True):
        specified[unit.bus_id] += complex(unit_result.p_mw, unit_result.q_mvar)  # type: ignore[arg-type]
    for source, source_result in zip(grid.external_grids, result.external_grids, strict=True):
        specified[source.bus_id] += complex(source_result.p_mw, source_result.q_mvar)  # type: ignore[arg-type]

    computed = injected_power_mva(grid, result)
    for bus_id, expected in specified.items():
        mismatch = computed[bus_id] - expected
        # The solver stops at 1e-8 MVA per bus; 1e-6 leaves two orders of margin.
        assert abs(mismatch) < 1e-6, f"bus {bus_id}: mismatch {mismatch} MVA"

    # The same check must be able to fail: a visibly wrong voltage breaks the balance.
    wrong = result.buses[4]
    perturbed = (*result.buses[:4], _replace_voltage(wrong, 1.001), *result.buses[5:])
    bad = injected_power_mva(grid, _with_buses(result, perturbed))
    assert max(abs(bad[bus_id] - specified[bus_id]) for bus_id in specified) > 0.1


def _replace_voltage(bus: Any, factor: float) -> Any:
    from dataclasses import replace

    return replace(bus, voltage_pu=bus.voltage_pu * factor)


def _with_buses(result: PowerFlowResult, buses: tuple[Any, ...]) -> PowerFlowResult:
    from dataclasses import replace

    return replace(result, buses=buses)


def test_case9_generators_hold_their_set_points_and_sources_cover_load_and_losses(
    solver: PowerFlowSolver,
) -> None:
    grid = grid_model_from_pandapower(pn.case9(), name="case9")
    result = run_power_flow(grid, solver)
    voltage = {bus.bus_id: bus.voltage_pu for bus in result.buses}

    for unit, unit_result in zip(grid.generators, result.generators, strict=True):
        assert voltage[unit.bus_id] == pytest.approx(unit.voltage_setpoint_pu, abs=1e-9)
        assert unit_result.reactive_limit_reached is False
    assert result.totals is not None
    assert result.totals.served_load_mw == pytest.approx(315.0)
    assert result.totals.generation_mw == pytest.approx(248.0)
    assert result.totals.external_supply_mw + result.totals.generation_mw == pytest.approx(
        315.0 + result.totals.active_losses_mw, abs=1e-6
    )
    assert 0 < result.totals.active_losses_mw < 0.05 * 315.0


def test_case9_matches_pandapower_solving_its_own_copy(solver: PowerFlowSolver) -> None:
    net = pn.case9()
    result = run_power_flow(grid_model_from_pandapower(net, name="case9"), solver)
    solve_with_pandapower(net, enforce_q_lims=True)

    for index, bus in enumerate(result.buses):
        assert bus.voltage_pu == pytest.approx(net.res_bus.vm_pu[index], abs=MAPPING_TOLERANCE)
        assert bus.voltage_angle_degree == pytest.approx(
            net.res_bus.va_degree[index], abs=MAPPING_TOLERANCE
        )
    for index, unit in enumerate(result.generators):
        assert unit.q_mvar == pytest.approx(net.res_gen.q_mvar[index], abs=1e-6)


# --- 2. CIGRE MV: the shipped data ----------------------------------------------------


def test_the_shipped_cigre_network_equals_the_pandapower_copy() -> None:
    net = _pandapower_cigre()
    assert cigre_mv.cigre_mv_with_der() == grid_model_from_pandapower(net, name=cigre_mv.NAME)
    assert bus_coordinates(net) == cigre_mv.BUS_DIAGRAM_COORDINATES


def test_the_shipped_cigre_network_is_valid_and_labelled_synthetic() -> None:
    grid = cigre_mv.cigre_mv_with_der()
    assert validate_grid(grid) == ()
    assert "synthetic" in grid.name.lower()
    assert "not a real network" in cigre_mv.DESCRIPTION.lower()
    assert (
        len(grid.buses),
        len(grid.lines),
        len(grid.transformers),
        len(grid.loads),
        len(grid.generators),
        len(grid.external_grids),
        len(grid.switches),
    ) == (15, 15, 2, 18, 9, 1, 8)
    assert sum(1 for switch in grid.switches if not switch.closed) == 3
    assert set(cigre_mv.BUS_DIAGRAM_COORDINATES) == {bus.id for bus in grid.buses}


def test_the_shipped_cigre_network_is_built_fresh_and_identically_each_time() -> None:
    assert cigre_mv.cigre_mv_with_der() == cigre_mv.cigre_mv_with_der()
    assert cigre_mv.cigre_mv_with_der() is not cigre_mv.cigre_mv_with_der()


# --- 3. CIGRE MV: results -------------------------------------------------------------


def test_cigre_results_match_pandapower_solving_its_own_copy(solver: PowerFlowSolver) -> None:
    net = _pandapower_cigre()
    result = run_power_flow(cigre_mv.cigre_mv_with_der(), solver)
    solve_with_pandapower(net)
    assert result.converged

    for index, bus in enumerate(result.buses):
        assert bus.voltage_pu == pytest.approx(net.res_bus.vm_pu[index], abs=MAPPING_TOLERANCE)
        assert bus.voltage_angle_degree == pytest.approx(
            net.res_bus.va_degree[index], abs=MAPPING_TOLERANCE
        )
    for index, line in enumerate(result.lines):
        assert line.energized is True
        assert line.p_from_mw == pytest.approx(net.res_line.p_from_mw[index], abs=MAPPING_TOLERANCE)
        assert line.q_to_mvar == pytest.approx(net.res_line.q_to_mvar[index], abs=MAPPING_TOLERANCE)
        assert line.current_ka == pytest.approx(net.res_line.i_ka[index], abs=MAPPING_TOLERANCE)
        assert line.loading_percent == pytest.approx(net.res_line.loading_percent[index], abs=1e-7)
    for index, transformer in enumerate(result.transformers):
        assert transformer.p_hv_mw == pytest.approx(
            net.res_trafo.p_hv_mw[index], abs=MAPPING_TOLERANCE
        )
        assert transformer.q_lv_mvar == pytest.approx(
            net.res_trafo.q_lv_mvar[index], abs=MAPPING_TOLERANCE
        )
        assert transformer.loading_percent == pytest.approx(
            net.res_trafo.loading_percent[index], abs=1e-7
        )
    (slack,) = result.external_grids
    assert slack.p_mw == pytest.approx(net.res_ext_grid.p_mw[0], abs=MAPPING_TOLERANCE)
    assert slack.q_mvar == pytest.approx(net.res_ext_grid.q_mvar[0], abs=MAPPING_TOLERANCE)


def test_cigre_normally_open_points_leave_three_lines_open_ended(
    solver: PowerFlowSolver,
) -> None:
    grid = cigre_mv.cigre_mv_with_der()
    energization = analyze_energization(grid)
    assert energization.bus_ids == {bus.id for bus in grid.buses}
    assert energization.line_ids == {line.id for line in grid.lines}

    result = run_power_flow(grid, solver)
    lines = {line.line_id: line for line in result.lines}
    open_ended = {switch.element_id for switch in grid.switches if not switch.closed}
    assert open_ended == {"line-6-7", "line-11-4", "line-14-8"}
    for line_id in open_ended:
        # Charging only: next to nothing compared with the loaded lines.
        assert lines[line_id].energized is True
        assert lines[line_id].loading_percent is not None
        assert lines[line_id].loading_percent < 0.5  # type: ignore[operator]
    assert lines["line-1-2"].loading_percent is not None
    assert lines["line-1-2"].loading_percent > 50


def test_cigre_totals_balance(solver: PowerFlowSolver) -> None:
    result = run_power_flow(cigre_mv.cigre_mv_with_der(), solver)
    totals = result.totals
    assert totals is not None
    assert totals.generation_mw == pytest.approx(1.71)
    assert totals.unserved_load_mw == 0.0
    assert totals.unavailable_generation_mw == 0.0
    assert totals.external_supply_mw + totals.generation_mw == pytest.approx(
        totals.served_load_mw + totals.active_losses_mw, abs=1e-6
    )
    line_losses = sum(line.active_loss_mw or 0.0 for line in result.lines)
    transformer_losses = sum(item.active_loss_mw or 0.0 for item in result.transformers)
    assert line_losses + transformer_losses == pytest.approx(totals.active_losses_mw, abs=1e-9)


def test_closing_the_cigre_ring_switches_still_solves_and_changes_the_flows(
    solver: PowerFlowSolver,
) -> None:
    from dataclasses import replace

    grid = cigre_mv.cigre_mv_with_der()
    meshed = replace(grid, switches=tuple(replace(switch, closed=True) for switch in grid.switches))
    radial_result = run_power_flow(grid, solver)
    meshed_result = run_power_flow(meshed, solver)

    assert meshed_result.converged
    tie = {line.line_id: line for line in meshed_result.lines}["line-6-7"]
    assert tie.loading_percent is not None
    assert tie.loading_percent > 1.0
    assert meshed_result.totals is not None
    assert radial_result.totals is not None
    assert meshed_result.totals.active_losses_mw != pytest.approx(
        radial_result.totals.active_losses_mw, abs=1e-6
    )
