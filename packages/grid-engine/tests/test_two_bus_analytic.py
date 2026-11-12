"""The engine against solutions that do not come from any power flow program.

A two-bus network (slack, one line, one constant-power load) has a closed-form solution.
With line-to-line voltages in kV, three-phase power in MW/MVAr and per-phase impedance in
ohm, and the receiving voltage V2 taken as the angle reference:

    V1 = V2 + (R + jX)(P - jQ) / V2

Taking magnitudes gives a quadratic in V2 squared:

    V2^4 + (2(PR + QX) - V1^2) V2^2 + (P^2 + Q^2)(R^2 + X^2) = 0

whose larger root is the operating point. Everything else follows from V2.
"""

import math
from dataclasses import dataclass

import pytest
from grid_factories import two_bus

from gridwise_grid_engine import PowerFlowSolver, run_power_flow

# Tolerances. The solver stops at a 1e-8 MVA bus mismatch; observed agreement with the
# closed form is around 1e-12, so these leave margin without hiding a real error.
VOLTAGE_TOLERANCE_PU = 1e-9
ANGLE_TOLERANCE_DEGREE = 1e-8
POWER_TOLERANCE_MW = 1e-8
CURRENT_TOLERANCE_KA = 1e-9
LOADING_TOLERANCE_PERCENT = 1e-6


@dataclass(frozen=True)
class ClosedForm:
    voltage_pu: float
    angle_degree: float
    current_ka: float
    loss_mw: float
    loss_mvar: float


def closed_form(v1_kv: float, r_ohm: float, x_ohm: float, p_mw: float, q_mvar: float) -> ClosedForm:
    a = v1_kv**2 - 2 * (p_mw * r_ohm + q_mvar * x_ohm)
    discriminant = a**2 - 4 * (p_mw**2 + q_mvar**2) * (r_ohm**2 + x_ohm**2)
    assert discriminant >= 0, "no operating point exists for these inputs"
    v2_kv = math.sqrt((a + math.sqrt(discriminant)) / 2)
    # Angle of V1 relative to V2; the result reports V2 relative to V1, hence the sign.
    delta = math.atan2(
        (x_ohm * p_mw - r_ohm * q_mvar) / v2_kv,
        v2_kv + (r_ohm * p_mw + x_ohm * q_mvar) / v2_kv,
    )
    apparent_squared = p_mw**2 + q_mvar**2
    return ClosedForm(
        voltage_pu=v2_kv / v1_kv,
        angle_degree=-math.degrees(delta),
        current_ka=math.sqrt(apparent_squared) / (math.sqrt(3) * v2_kv),
        loss_mw=apparent_squared / v2_kv**2 * r_ohm,
        loss_mvar=apparent_squared / v2_kv**2 * x_ohm,
    )


def test_reference_case_matches_hand_calculated_constants(solver: PowerFlowSolver) -> None:
    """20 kV, R = 1.0 ohm, X = 0.5 ohm, 4 MW + 1.5 MVAr. Constants computed independently."""
    result = run_power_flow(two_bus(), solver)

    assert result.converged
    assert result.failure_code is None
    source, load = result.buses
    (line,) = result.lines
    (slack,) = result.external_grids
    assert result.totals is not None

    assert source.voltage_pu == pytest.approx(1.0, abs=VOLTAGE_TOLERANCE_PU)
    assert source.voltage_angle_degree == pytest.approx(0.0, abs=ANGLE_TOLERANCE_DEGREE)
    assert load.voltage_pu == pytest.approx(0.9879797221653659, abs=VOLTAGE_TOLERANCE_PU)
    assert load.voltage_angle_degree == pytest.approx(
        -0.07249110674251742, abs=ANGLE_TOLERANCE_DEGREE
    )

    assert line.p_from_mw == pytest.approx(4.046741948814914, abs=POWER_TOLERANCE_MW)
    assert line.q_from_mvar == pytest.approx(1.5233709744074568, abs=POWER_TOLERANCE_MW)
    assert line.p_to_mw == pytest.approx(-4.0, abs=POWER_TOLERANCE_MW)
    assert line.q_to_mvar == pytest.approx(-1.5, abs=POWER_TOLERANCE_MW)
    assert line.active_loss_mw == pytest.approx(0.046741948814913614, abs=POWER_TOLERANCE_MW)
    assert line.reactive_loss_mvar == pytest.approx(0.023370974407456807, abs=POWER_TOLERANCE_MW)
    assert line.current_ka == pytest.approx(0.12482247235562674, abs=CURRENT_TOLERANCE_KA)
    assert line.loading_percent == pytest.approx(41.60749078520892, abs=LOADING_TOLERANCE_PERCENT)

    assert slack.p_mw == pytest.approx(4.046741948814914, abs=POWER_TOLERANCE_MW)
    assert slack.q_mvar == pytest.approx(1.5233709744074568, abs=POWER_TOLERANCE_MW)
    # Bus sign convention: power withdrawn from the network is positive.
    assert load.p_mw == pytest.approx(4.0, abs=POWER_TOLERANCE_MW)
    assert source.p_mw == pytest.approx(-4.046741948814914, abs=POWER_TOLERANCE_MW)

    assert result.totals.served_load_mw == 4.0
    assert result.totals.unserved_load_mw == 0.0
    assert result.totals.active_losses_mw == pytest.approx(
        0.046741948814913614, abs=POWER_TOLERANCE_MW
    )


@pytest.mark.parametrize(
    ("kv", "slack_pu", "length_km", "r", "x", "p", "q"),
    [
        (20.0, 1.0, 5.0, 0.2, 0.1, 4.0, 1.5),
        (20.0, 1.03, 12.0, 0.31, 0.12, 6.0, 2.0),  # raised set-point, longer line
        (10.0, 1.0, 3.0, 0.4, 0.09, 1.2, -0.4),  # capacitive load
        (110.0, 1.0, 40.0, 0.06, 0.4, 60.0, 20.0),  # high voltage, X >> R
        (0.4, 1.0, 0.25, 0.32, 0.08, 0.05, 0.02),  # low voltage
        (20.0, 1.0, 8.0, 0.25, 0.0, 3.0, 0.0),  # purely resistive line, unity power factor
    ],
)
def test_matches_the_closed_form_solution(
    solver: PowerFlowSolver,
    kv: float,
    slack_pu: float,
    length_km: float,
    r: float,
    x: float,
    p: float,
    q: float,
) -> None:
    expected = closed_form(kv * slack_pu, r * length_km, x * length_km, p, q)
    # closed_form works in per unit of the slack voltage; the engine in per unit of nominal.
    expected_pu = expected.voltage_pu * slack_pu

    result = run_power_flow(
        two_bus(
            nominal_voltage_kv=kv,
            slack_voltage_pu=slack_pu,
            length_km=length_km,
            r_ohm_per_km=r,
            x_ohm_per_km=x,
            max_i_ka=1.0,
            p_mw=p,
            q_mvar=q,
        ),
        solver,
    )

    assert result.converged
    _, load = result.buses
    (line,) = result.lines
    assert load.voltage_pu == pytest.approx(expected_pu, abs=VOLTAGE_TOLERANCE_PU)
    assert load.voltage_angle_degree == pytest.approx(
        expected.angle_degree, abs=ANGLE_TOLERANCE_DEGREE
    )
    assert line.active_loss_mw == pytest.approx(expected.loss_mw, abs=POWER_TOLERANCE_MW)
    assert line.reactive_loss_mvar == pytest.approx(expected.loss_mvar, abs=POWER_TOLERANCE_MW)
    assert line.current_ka == pytest.approx(expected.current_ka, abs=CURRENT_TOLERANCE_KA)
    assert line.loading_percent == pytest.approx(
        expected.current_ka / 1.0 * 100, abs=LOADING_TOLERANCE_PERCENT
    )


def test_no_load_means_no_drop_and_no_flow(solver: PowerFlowSolver) -> None:
    result = run_power_flow(two_bus(p_mw=0.0, q_mvar=0.0, slack_voltage_pu=1.02), solver)
    _, load = result.buses
    (line,) = result.lines
    assert load.voltage_pu == pytest.approx(1.02, abs=VOLTAGE_TOLERANCE_PU)
    assert load.voltage_angle_degree == pytest.approx(0.0, abs=ANGLE_TOLERANCE_DEGREE)
    assert line.current_ka == pytest.approx(0.0, abs=CURRENT_TOLERANCE_KA)
    assert line.active_loss_mw == pytest.approx(0.0, abs=POWER_TOLERANCE_MW)


@pytest.mark.parametrize("frequency_hz", [50.0, 60.0])
def test_line_charging_matches_the_pi_model_at_no_load(
    solver: PowerFlowSolver, frequency_hz: float
) -> None:
    """Checks the capacitance unit (nF/km) and that frequency is really used.

    For a nominal pi line with an open far end, V2 / V1 = 1 / |1 + Z * Y / 2| with
    Z = (r + jx) * l and Y = j * 2 * pi * f * c * l. The voltage rises (Ferranti effect).
    """
    length_km, r, x, c_nf = 30.0, 0.12, 0.11, 280.0
    impedance = complex(r, x) * length_km
    admittance = 1j * 2 * math.pi * frequency_hz * c_nf * 1e-9 * length_km
    expected_pu = 1 / abs(1 + impedance * admittance / 2)
    assert expected_pu > 1.0

    result = run_power_flow(
        two_bus(
            nominal_voltage_kv=110.0,
            length_km=length_km,
            r_ohm_per_km=r,
            x_ohm_per_km=x,
            c_nf_per_km=c_nf,
            p_mw=0.0,
            q_mvar=0.0,
            frequency_hz=frequency_hz,
        ),
        solver,
    )
    _, load = result.buses
    assert load.voltage_pu == pytest.approx(expected_pu, abs=VOLTAGE_TOLERANCE_PU)
    # The line generates reactive power, so its reactive "loss" is negative.
    assert result.lines[0].reactive_loss_mvar is not None
    assert result.lines[0].reactive_loss_mvar < 0
