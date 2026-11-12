import math
from dataclasses import replace

import pytest
from grid_factories import three_bus_radial, two_bus

from gridwise_grid_engine import PowerFlowOptions, grid_hash, result_hash, run_power_flow
from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
from gridwise_grid_engine.hashing import RESULT_HASH_DECIMALS

# A regression value recorded on macOS arm64, not a validation of the physics. Whether
# Linux x86-64 reproduces it is only known once CI has run this test there.
TWO_BUS_RESULT_HASH = "b571c1b586c4f37692ea33faca9f701c348a3706ca96914021f5401519215664"


def test_identical_inputs_give_identical_result_hashes(solver: PandapowerSolver) -> None:
    first = run_power_flow(three_bus_radial(), solver)
    second = run_power_flow(three_bus_radial(), solver)
    assert first == second  # every value, bit for bit, on one machine
    assert result_hash(first) == result_hash(second)


def test_a_fresh_solver_instance_gives_the_same_hash(solver: PandapowerSolver) -> None:
    assert result_hash(run_power_flow(two_bus(), solver)) == result_hash(
        run_power_flow(two_bus(), PandapowerSolver())
    )


def test_the_normalised_hash_is_stable_across_platforms(solver: PandapowerSolver) -> None:
    assert result_hash(run_power_flow(two_bus(), solver)) == TWO_BUS_RESULT_HASH


def test_solving_something_else_in_between_changes_nothing(solver: PandapowerSolver) -> None:
    before = result_hash(run_power_flow(two_bus(), solver))
    run_power_flow(three_bus_radial(), solver)
    run_power_flow(two_bus(p_mw=9.0), solver)
    assert result_hash(run_power_flow(two_bus(), solver)) == before


def test_element_order_does_not_change_either_hash(solver: PandapowerSolver) -> None:
    grid = three_bus_radial()
    shuffled = replace(
        grid,
        buses=tuple(reversed(grid.buses)),
        lines=tuple(reversed(grid.lines)),
        loads=tuple(reversed(grid.loads)),
    )
    assert grid_hash(shuffled) == grid_hash(grid)
    assert result_hash(run_power_flow(shuffled, solver)) == result_hash(
        run_power_flow(grid, solver)
    )


def test_any_input_change_changes_both_hashes(solver: PandapowerSolver) -> None:
    base, changed = two_bus(), two_bus(p_mw=4.000001)
    assert grid_hash(changed) != grid_hash(base)
    assert result_hash(run_power_flow(changed, solver)) != result_hash(run_power_flow(base, solver))


def test_options_are_part_of_the_result_identity(solver: PandapowerSolver) -> None:
    loose = run_power_flow(two_bus(), solver, PowerFlowOptions(tolerance_mva=1e-6))
    assert result_hash(loose) != result_hash(run_power_flow(two_bus(), solver))


def test_options_are_hashed_exactly_not_rounded(solver: PandapowerSolver) -> None:
    """Both tolerances are far below the result rounding; they must still differ."""
    default = run_power_flow(two_bus(), solver, PowerFlowOptions(tolerance_mva=1e-8))
    tighter = run_power_flow(two_bus(), solver, PowerFlowOptions(tolerance_mva=1e-10))
    assert result_hash(default) != result_hash(tighter)

    more_iterations = run_power_flow(two_bus(), solver, PowerFlowOptions(max_iterations=11))
    assert result_hash(default) != result_hash(more_iterations)


def test_how_a_number_is_written_does_not_change_the_hashes(solver: PandapowerSolver) -> None:
    """50 and 50.0 Hz, 4 and 4.0 MW, -0.0 and 0.0 MVAr are the same inputs."""
    as_floats = two_bus(frequency_hz=50.0, p_mw=4.0, q_mvar=0.0, length_km=5.0)
    as_ints = two_bus(frequency_hz=50, p_mw=4, q_mvar=0, length_km=5)
    negative_zero = two_bus(frequency_hz=50.0, p_mw=4.0, q_mvar=-0.0, length_km=5.0)

    assert grid_hash(as_ints) == grid_hash(as_floats)
    assert grid_hash(negative_zero) == grid_hash(as_floats)
    reference = result_hash(run_power_flow(as_floats, solver))
    assert result_hash(run_power_flow(as_ints, solver)) == reference
    assert result_hash(run_power_flow(negative_zero, solver)) == reference


def test_a_boolean_is_not_mistaken_for_a_number_when_hashing() -> None:
    in_service = two_bus()
    out_of_service = replace(
        in_service, loads=tuple(replace(load, in_service=False) for load in in_service.loads)
    )
    assert grid_hash(out_of_service) != grid_hash(in_service)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_cannot_be_hashed(bad: float, solver: PandapowerSolver) -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        grid_hash(two_bus(p_mw=bad))

    result = run_power_flow(two_bus(), solver)
    corrupted = replace(result, buses=tuple(replace(bus, voltage_pu=bad) for bus in result.buses))
    with pytest.raises(ValueError, match="Out of range float"):
        result_hash(corrupted)


def test_noise_below_the_normalisation_precision_does_not_change_the_hash(
    solver: PandapowerSolver,
) -> None:
    result = run_power_flow(two_bus(), solver)
    noise = 10 ** -(RESULT_HASH_DECIMALS + 4)
    nudged = replace(
        result,
        buses=tuple(
            replace(bus, voltage_pu=bus.voltage_pu + noise) if bus.voltage_pu is not None else bus
            for bus in result.buses
        ),
    )
    assert nudged != result
    assert result_hash(nudged) == result_hash(result)


def test_a_difference_at_the_normalisation_precision_does_change_the_hash(
    solver: PandapowerSolver,
) -> None:
    result = run_power_flow(two_bus(), solver)
    step = 10**-RESULT_HASH_DECIMALS
    nudged = replace(
        result,
        buses=tuple(
            replace(bus, voltage_pu=bus.voltage_pu + step) if bus.voltage_pu is not None else bus
            for bus in result.buses
        ),
    )
    assert result_hash(nudged) != result_hash(result)


def test_negative_zero_and_zero_hash_the_same(solver: PandapowerSolver) -> None:
    result = run_power_flow(two_bus(p_mw=0.0, q_mvar=0.0), solver)
    flipped = replace(
        result,
        buses=tuple(replace(bus, voltage_angle_degree=-0.0) for bus in result.buses),
    )
    zeroed = replace(
        result,
        buses=tuple(replace(bus, voltage_angle_degree=0.0) for bus in result.buses),
    )
    assert result_hash(flipped) == result_hash(zeroed)
