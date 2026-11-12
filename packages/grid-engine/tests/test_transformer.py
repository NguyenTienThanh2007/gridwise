"""The transformer model against solutions that do not come from a power flow program.

Three independent references:

1. With iron losses and no-load current set to zero, a transformer is a series impedance.
   Referred to the low-voltage side, its magnitude follows from the definition of the
   short-circuit voltage (the fraction of rated voltage that drives rated current through
   the short-circuited transformer):

       |Z| = vk / 100 * V_rated_lv^2 / S_rated          R = vkr / 100 * V_rated_lv^2 / S_rated

   and the two-bus closed form of test_two_bus_analytic.py applies unchanged.
2. At no load, with no magnetising branch, no current flows and the voltages are related by
   the turns ratio alone, including the tap position and rated voltages that differ from
   the buses' nominal voltages.
3. At no load, the iron losses and no-load current are what the transformer draws, by
   definition of those two nameplate values.
"""

import math

import pytest
from grid_factories import transformer_feeder
from test_two_bus_analytic import (
    ANGLE_TOLERANCE_DEGREE,
    POWER_TOLERANCE_MW,
    VOLTAGE_TOLERANCE_PU,
    closed_form,
)

from gridwise_grid_engine import PowerFlowSolver, TapChanger, run_power_flow


def series_impedance_lv_ohm(
    vk_percent: float, vkr_percent: float, rated_lv_kv: float, rated_mva: float
) -> tuple[float, float]:
    z = vk_percent / 100 * rated_lv_kv**2 / rated_mva
    r = vkr_percent / 100 * rated_lv_kv**2 / rated_mva
    return r, math.sqrt(z**2 - r**2)


@pytest.mark.parametrize(
    ("p_mw", "q_mvar", "vk", "vkr", "slack_pu"),
    [
        (10.0, 3.0, 12.0, 0.16, 1.0),
        (20.0, 8.0, 12.0, 0.16, 1.03),
        (5.0, -2.0, 6.0, 1.0, 0.98),  # capacitive load
        (0.4, 0.1, 4.0, 1.2, 1.0),
    ],
)
def test_a_lossless_core_transformer_is_a_series_impedance(
    solver: PowerFlowSolver, p_mw: float, q_mvar: float, vk: float, vkr: float, slack_pu: float
) -> None:
    grid = transformer_feeder(
        p_mw=p_mw,
        q_mvar=q_mvar,
        short_circuit_voltage_percent=vk,
        short_circuit_resistive_percent=vkr,
        slack_voltage_pu=slack_pu,
    )
    r_ohm, x_ohm = series_impedance_lv_ohm(vk, vkr, 20.0, 25.0)
    # The slack voltage, seen from the 20 kV side through the 110/20 ratio.
    expected = closed_form(slack_pu * 20.0, r_ohm, x_ohm, p_mw, q_mvar)

    result = run_power_flow(grid, solver)
    assert result.converged
    _, lv = result.buses
    (transformer,) = result.transformers

    assert lv.voltage_pu == pytest.approx(expected.voltage_pu * slack_pu, abs=VOLTAGE_TOLERANCE_PU)
    assert lv.voltage_angle_degree == pytest.approx(
        expected.angle_degree, abs=ANGLE_TOLERANCE_DEGREE
    )
    assert transformer.active_loss_mw == pytest.approx(expected.loss_mw, abs=POWER_TOLERANCE_MW)
    assert transformer.reactive_loss_mvar == pytest.approx(
        expected.loss_mvar, abs=POWER_TOLERANCE_MW
    )
    assert transformer.p_lv_mw == pytest.approx(-p_mw, abs=POWER_TOLERANCE_MW)
    assert transformer.q_lv_mvar == pytest.approx(-q_mvar, abs=POWER_TOLERANCE_MW)
    assert transformer.current_lv_ka == pytest.approx(expected.current_ka, abs=1e-9)
    # The same current on the other side of the ratio.
    assert transformer.current_hv_ka == pytest.approx(expected.current_ka * 20 / 110, abs=1e-9)


def test_loading_is_the_winding_current_relative_to_its_rated_current(
    solver: PowerFlowSolver,
) -> None:
    result = run_power_flow(transformer_feeder(), solver)
    (transformer,) = result.transformers
    assert transformer.current_hv_ka is not None
    assert transformer.current_lv_ka is not None
    rated_hv_ka = 25.0 / (math.sqrt(3) * 110.0)
    rated_lv_ka = 25.0 / (math.sqrt(3) * 20.0)
    expected = 100 * max(
        transformer.current_hv_ka / rated_hv_ka, transformer.current_lv_ka / rated_lv_ka
    )
    assert transformer.loading_percent == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("side", ["hv", "lv"])
@pytest.mark.parametrize("position", [-9, -2, 0, 3, 9])
def test_the_tap_changer_scales_the_no_load_voltage(
    solver: PowerFlowSolver, side: str, position: int
) -> None:
    """Each step changes the tapped winding's voltage by ``step_percent``.

    More turns on the high-voltage winding lower the low-voltage side; more turns on the
    low-voltage winding raise it.
    """
    step_percent = 1.5
    grid = transformer_feeder(
        p_mw=0.0,
        q_mvar=0.0,
        slack_voltage_pu=1.02,
        tap=TapChanger(
            side=side,
            neutral_position=0,
            min_position=-9,
            max_position=9,
            step_percent=step_percent,
            position=position,
        ),
    )
    factor = 1 + position * step_percent / 100
    expected = 1.02 / factor if side == "hv" else 1.02 * factor

    result = run_power_flow(grid, solver)
    _, lv = result.buses
    assert lv.voltage_pu == pytest.approx(expected, abs=VOLTAGE_TOLERANCE_PU)


def test_a_neutral_position_other_than_zero_is_respected(solver: PowerFlowSolver) -> None:
    tap = TapChanger(
        side="hv", neutral_position=5, min_position=1, max_position=9, step_percent=2.0, position=3
    )
    result = run_power_flow(transformer_feeder(p_mw=0.0, q_mvar=0.0, tap=tap), solver)
    _, lv = result.buses
    assert lv.voltage_pu == pytest.approx(1 / (1 + (3 - 5) * 0.02), abs=VOLTAGE_TOLERANCE_PU)


def test_rated_voltages_that_differ_from_the_bus_voltages_set_the_ratio(
    solver: PowerFlowSolver,
) -> None:
    """A 115/21 kV unit between a 110 kV and a 20 kV bus: per unit, (110/115) * (21/20)."""
    grid = transformer_feeder(
        p_mw=0.0, q_mvar=0.0, rated_voltage_hv_kv=115.0, rated_voltage_lv_kv=21.0
    )
    _, lv = run_power_flow(grid, solver).buses
    assert lv.voltage_pu == pytest.approx((110 / 115) * (21 / 20), abs=VOLTAGE_TOLERANCE_PU)


def test_the_phase_shift_turns_the_low_voltage_angle(solver: PowerFlowSolver) -> None:
    plain = run_power_flow(transformer_feeder(), solver).buses[1]
    shifted = run_power_flow(transformer_feeder(phase_shift_degree=30.0), solver).buses[1]
    assert shifted.voltage_pu == pytest.approx(plain.voltage_pu, abs=VOLTAGE_TOLERANCE_PU)
    assert plain.voltage_angle_degree is not None
    assert shifted.voltage_angle_degree == pytest.approx(
        plain.voltage_angle_degree - 30.0, abs=ANGLE_TOLERANCE_DEGREE
    )


def test_an_unloaded_transformer_draws_its_no_load_power(solver: PowerFlowSolver) -> None:
    """Iron losses 14 kW; no-load current 0.07 % of 25 MVA = 17.5 kVA.

    Reactive part: sqrt(17.5^2 - 14^2) = 10.5 kVAr. The tolerance of 0.1 % of each value
    covers the small voltage drop over half the series impedance in the T equivalent
    circuit, which sits between the terminal and the magnetising branch.
    """
    grid = transformer_feeder(
        p_mw=0.0, q_mvar=0.0, iron_losses_kw=14.0, no_load_current_percent=0.07
    )
    result = run_power_flow(grid, solver)
    (transformer,) = result.transformers
    (slack,) = result.external_grids

    assert transformer.p_hv_mw == pytest.approx(0.014, rel=1e-3)
    assert transformer.q_hv_mvar == pytest.approx(0.0105, rel=1e-3)
    assert transformer.active_loss_mw == pytest.approx(0.014, rel=1e-3)
    assert transformer.p_lv_mw == pytest.approx(0.0, abs=POWER_TOLERANCE_MW)
    assert slack.p_mw == pytest.approx(transformer.p_hv_mw, abs=POWER_TOLERANCE_MW)
    assert result.totals is not None
    assert result.totals.active_losses_mw == pytest.approx(transformer.active_loss_mw)


def test_an_out_of_service_transformer_has_no_values(solver: PowerFlowSolver) -> None:
    from dataclasses import replace

    grid = transformer_feeder()
    off = replace(grid, transformers=(replace(grid.transformers[0], in_service=False),))
    result = run_power_flow(off, solver)

    (transformer,) = result.transformers
    assert transformer.energized is False
    assert transformer.p_hv_mw is None
    assert transformer.current_lv_ka is None
    assert transformer.loading_percent is None
    assert result.buses[1].voltage_pu is None
    assert result.unsupplied_bus_ids == ("lv",)
    assert result.totals is not None
    assert result.totals.unserved_load_mw == pytest.approx(10.0)
