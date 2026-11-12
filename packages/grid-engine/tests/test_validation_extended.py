"""Validation of transformers, generators and switches: one stable code per rule."""

import math
from dataclasses import replace

import pytest
from grid_factories import (
    constant_power_generator,
    substation_feeder,
    switch,
    three_bus_radial,
    transformer_feeder,
    two_bus,
    voltage_controlled_generator,
)
from test_validation import CountingSolver, codes

from gridwise_grid_engine import (
    Bus,
    ErrorCode,
    ExternalGrid,
    Generator,
    GridModel,
    GridValidationError,
    Switch,
    TapChanger,
    run_power_flow,
    validate_grid,
)


def with_transformer(grid: GridModel, **changes: object) -> GridModel:
    return replace(
        grid,
        transformers=tuple(replace(t, **changes) for t in grid.transformers),  # type: ignore[arg-type]
    )


def with_generator(grid: GridModel, generator: Generator) -> GridModel:
    return replace(grid, generators=(generator,))


def with_switch(grid: GridModel, item: Switch) -> GridModel:
    return replace(grid, switches=(item,))


def tap(**changes: object) -> TapChanger:
    base = TapChanger(
        side="hv", neutral_position=0, min_position=-9, max_position=9, step_percent=1.5, position=0
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_the_extended_test_grids_are_valid() -> None:
    assert validate_grid(transformer_feeder()) == ()
    assert validate_grid(transformer_feeder(tap=tap(position=3))) == ()
    assert validate_grid(substation_feeder()) == ()


# --- transformer ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"rated_power_mva": 0.0}, ErrorCode.INVALID_TRANSFORMER_RATED_POWER),
        ({"rated_power_mva": -25.0}, ErrorCode.INVALID_TRANSFORMER_RATED_POWER),
        ({"rated_voltage_lv_kv": 0.0}, ErrorCode.INVALID_TRANSFORMER_RATED_VOLTAGE),
        ({"rated_voltage_hv_kv": 20.0}, ErrorCode.INVALID_TRANSFORMER_RATED_VOLTAGE),  # = LV
        ({"rated_voltage_hv_kv": 10.0}, ErrorCode.INVALID_TRANSFORMER_RATED_VOLTAGE),  # < LV
        (
            {"short_circuit_voltage_percent": 0.0},
            ErrorCode.INVALID_TRANSFORMER_SHORT_CIRCUIT_VOLTAGE,
        ),
        (
            {"short_circuit_resistive_percent": -0.1},
            ErrorCode.INVALID_TRANSFORMER_SHORT_CIRCUIT_VOLTAGE,
        ),
        (
            {"short_circuit_resistive_percent": 12.5},  # larger than the total, 12 %
            ErrorCode.INVALID_TRANSFORMER_SHORT_CIRCUIT_VOLTAGE,
        ),
        ({"iron_losses_kw": -1.0}, ErrorCode.NEGATIVE_TRANSFORMER_IRON_LOSSES),
        ({"no_load_current_percent": -0.01}, ErrorCode.INVALID_TRANSFORMER_NO_LOAD_CURRENT),
    ],
)
def test_invalid_transformer_parameters(changes: dict[str, object], expected: ErrorCode) -> None:
    assert codes(with_transformer(transformer_feeder(), **changes)) == {expected}


def test_no_load_current_must_cover_the_iron_losses() -> None:
    """14 kW on 25 MVA needs at least 14 / (10 * 25) = 0.056 % no-load current."""
    too_small = transformer_feeder(iron_losses_kw=14.0, no_load_current_percent=0.05)
    assert codes(too_small) == {ErrorCode.INVALID_TRANSFORMER_NO_LOAD_CURRENT}
    exactly = transformer_feeder(iron_losses_kw=14.0, no_load_current_percent=0.056)
    assert validate_grid(exactly) == ()
    assert (
        validate_grid(transformer_feeder(iron_losses_kw=14.0, no_load_current_percent=0.07)) == ()
    )


def test_a_purely_resistive_short_circuit_voltage_is_allowed() -> None:
    grid = with_transformer(
        transformer_feeder(), short_circuit_voltage_percent=4.0, short_circuit_resistive_percent=4.0
    )
    assert validate_grid(grid) == ()


def test_a_transformer_cannot_connect_a_bus_to_itself() -> None:
    grid = with_transformer(transformer_feeder(), lv_bus_id="hv")
    assert codes(grid) == {ErrorCode.TRANSFORMER_CONNECTS_BUS_TO_ITSELF}


def test_a_transformer_must_step_down_from_its_hv_bus_to_its_lv_bus() -> None:
    swapped = with_transformer(transformer_feeder(), hv_bus_id="lv", lv_bus_id="hv")
    assert codes(swapped) == {ErrorCode.TRANSFORMER_VOLTAGE_MISMATCH}

    same_level = replace(
        transformer_feeder(),
        buses=(
            Bus(id="hv", name="HV", nominal_voltage_kv=20.0),
            Bus(id="lv", name="LV", nominal_voltage_kv=20.0),
        ),
    )
    assert codes(same_level) == {ErrorCode.TRANSFORMER_VOLTAGE_MISMATCH}


def test_a_transformer_on_an_unknown_bus() -> None:
    grid = with_transformer(transformer_feeder(), lv_bus_id="nowhere")
    assert ErrorCode.UNKNOWN_BUS_REFERENCE in codes(grid)


@pytest.mark.parametrize("bad", [math.nan, math.inf, "12", None, True])
def test_transformer_values_must_be_finite_real_numbers(bad: object) -> None:
    grid = with_transformer(transformer_feeder(), short_circuit_voltage_percent=bad)
    assert codes(grid) == {ErrorCode.INVALID_NUMBER}


@pytest.mark.parametrize(
    "changes",
    [
        {"side": "mv"},
        {"side": None},
        {"step_percent": 0.0},
        {"step_percent": -1.5},
        {"step_percent": math.nan},
        {"position": 10},  # above max_position
        {"position": -10},
        {"position": 1.0},  # a float is not a tap position
        {"position": True},
        {"neutral_position": 12},
        {"min_position": 5, "max_position": -5},
        {"max_position": "9"},
    ],
)
def test_invalid_tap_changers(changes: dict[str, object]) -> None:
    grid = transformer_feeder(tap=tap(**changes))
    assert codes(grid) == {ErrorCode.INVALID_TAP_CHANGER}


def test_tap_issues_name_the_field() -> None:
    (issue,) = validate_grid(transformer_feeder(tap=tap(position=10)))
    assert (issue.element_type, issue.element_id, issue.field) == (
        "transformer",
        "t1",
        "tap.position",
    )


# --- generator ------------------------------------------------------------------------


def test_valid_generators_in_both_modes() -> None:
    assert (
        validate_grid(with_generator(two_bus(), constant_power_generator("load", 2.0, 0.5))) == ()
    )
    assert (
        validate_grid(with_generator(two_bus(), voltage_controlled_generator("load", 2.0, 1.01)))
        == ()
    )
    limited = voltage_controlled_generator("load", 2.0, 1.01, min_q_mvar=-1.0, max_q_mvar=1.0)
    assert validate_grid(with_generator(two_bus(), limited)) == ()


@pytest.mark.parametrize(
    ("generator", "expected"),
    [
        (
            replace(constant_power_generator("load", -1.0)),
            ErrorCode.NEGATIVE_GENERATOR_ACTIVE_POWER,
        ),
        (
            replace(constant_power_generator("load", 1.0), control_mode="droop"),
            ErrorCode.INVALID_GENERATOR_CONTROL_MODE,
        ),
        (
            replace(constant_power_generator("load", 1.0), q_mvar=None),
            ErrorCode.INVALID_GENERATOR_PARAMETERS,
        ),
        (
            replace(constant_power_generator("load", 1.0), voltage_setpoint_pu=1.0),
            ErrorCode.INVALID_GENERATOR_PARAMETERS,
        ),
        (
            replace(constant_power_generator("load", 1.0), max_q_mvar=1.0),
            ErrorCode.INVALID_GENERATOR_PARAMETERS,
        ),
        (
            replace(voltage_controlled_generator("load", 1.0, 1.0), voltage_setpoint_pu=None),
            ErrorCode.INVALID_GENERATOR_PARAMETERS,
        ),
        (
            replace(voltage_controlled_generator("load", 1.0, 1.0), q_mvar=0.5),
            ErrorCode.INVALID_GENERATOR_PARAMETERS,
        ),
        (
            voltage_controlled_generator("load", 1.0, 0.0),
            ErrorCode.INVALID_GENERATOR_VOLTAGE_SETPOINT,
        ),
        (
            voltage_controlled_generator("load", 1.0, -1.0),
            ErrorCode.INVALID_GENERATOR_VOLTAGE_SETPOINT,
        ),
        (
            voltage_controlled_generator("load", 1.0, 1.0, min_q_mvar=1.0, max_q_mvar=-1.0),
            ErrorCode.INVALID_GENERATOR_REACTIVE_LIMITS,
        ),
        (
            voltage_controlled_generator("load", 1.0, 1.0, min_q_mvar=-1.0),
            ErrorCode.INVALID_GENERATOR_REACTIVE_LIMITS,
        ),
        (
            replace(constant_power_generator("load", 1.0), rated_power_mva=0.0),
            ErrorCode.INVALID_GENERATOR_RATED_POWER,
        ),
        (
            replace(constant_power_generator("load", 3.0, 4.0), rated_power_mva=4.9),  # 5 MVA
            ErrorCode.GENERATOR_EXCEEDS_RATED_POWER,
        ),
        (
            replace(voltage_controlled_generator("load", 3.0, 1.0), rated_power_mva=2.9),
            ErrorCode.GENERATOR_EXCEEDS_RATED_POWER,
        ),
    ],
)
def test_invalid_generators(generator: Generator, expected: ErrorCode) -> None:
    assert codes(with_generator(two_bus(), generator)) == {expected}


def test_a_generator_exactly_at_its_rating_is_allowed() -> None:
    unit = replace(constant_power_generator("load", 3.0, 4.0), rated_power_mva=5.0)
    assert validate_grid(with_generator(two_bus(), unit)) == ()


def test_equal_reactive_limits_are_allowed() -> None:
    unit = voltage_controlled_generator("load", 1.0, 1.0, min_q_mvar=0.3, max_q_mvar=0.3)
    assert validate_grid(with_generator(two_bus(), unit)) == ()


@pytest.mark.parametrize("field", ["p_mw", "q_mvar", "rated_power_mva"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, "1", True])
def test_generator_values_must_be_finite_real_numbers(field: str, bad: object) -> None:
    unit = replace(constant_power_generator("load", 1.0), **{field: bad})  # type: ignore[arg-type]
    assert ErrorCode.INVALID_NUMBER in codes(with_generator(two_bus(), unit))


def test_a_generator_on_an_unknown_bus() -> None:
    grid = with_generator(two_bus(), constant_power_generator("nowhere", 1.0))
    assert codes(grid) == {ErrorCode.UNKNOWN_BUS_REFERENCE}


def test_a_voltage_controlled_generator_cannot_share_a_bus_with_an_external_grid() -> None:
    grid = with_generator(two_bus(), voltage_controlled_generator("source", 1.0, 1.0))
    assert codes(grid) == {ErrorCode.MULTIPLE_VOLTAGE_CONTROLLERS_ON_BUS}


def test_two_voltage_controlled_generators_cannot_share_a_bus() -> None:
    first = voltage_controlled_generator("load", 1.0, 1.0)
    second = replace(first, id="second")  # even with the same set-point
    grid = replace(two_bus(), generators=(first, second))
    assert codes(grid) == {ErrorCode.MULTIPLE_VOLTAGE_CONTROLLERS_ON_BUS}


def test_units_that_cannot_conflict_may_share_a_bus() -> None:
    controlled = voltage_controlled_generator("load", 1.0, 1.0)
    grid = replace(
        two_bus(),
        generators=(
            controlled,
            replace(constant_power_generator("load", 0.5), id="embedded"),
            replace(controlled, id="standby", in_service=False),
        ),
    )
    assert validate_grid(grid) == ()
    # A constant-power unit next to the external grid is fine too.
    assert validate_grid(with_generator(two_bus(), constant_power_generator("source", 1.0))) == ()


def test_a_generator_is_not_a_slack_source() -> None:
    grid = replace(
        with_generator(two_bus(), voltage_controlled_generator("load", 5.0, 1.0)),
        external_grids=(),
    )
    assert codes(grid) == {ErrorCode.MISSING_EXTERNAL_GRID}


# --- switch ---------------------------------------------------------------------------


def test_valid_switches_of_every_kind() -> None:
    grid = replace(
        substation_feeder(),
        buses=(*substation_feeder().buses, Bus(id="d", name="D", nominal_voltage_kv=20.0)),
        switches=(
            switch("s1", "a", "line", "ab"),
            switch("s2", "b", "line", "ab", closed=False),
            switch("s3", "hv", "transformer", "t1"),
            switch("s4", "a", "transformer", "t1"),
            switch("s5", "c", "bus", "d", closed=False),
        ),
    )
    assert validate_grid(grid) == ()


@pytest.mark.parametrize("bad", ["open", "true", None, 0, 1, []])
def test_closed_must_be_a_real_boolean(bad: object) -> None:
    item = replace(switch("s", "a", "line", "ab"), closed=bad)  # type: ignore[arg-type]
    assert codes(with_switch(three_bus_radial(), item)) == {ErrorCode.INVALID_SWITCH_STATE}


def test_an_invalid_switch_state_never_reaches_the_solver() -> None:
    item = replace(switch("s", "a", "line", "ab"), closed="open")  # type: ignore[arg-type]
    solver = CountingSolver()
    with pytest.raises(GridValidationError) as raised:
        run_power_flow(with_switch(three_bus_radial(), item), solver)
    assert raised.value.codes == {ErrorCode.INVALID_SWITCH_STATE}
    assert solver.calls == 0


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (switch("s", "a", "cable", "ab"), ErrorCode.INVALID_SWITCH_ELEMENT_TYPE),
        (replace(switch("s", "a", "line", "ab"), kind="fuse"), ErrorCode.INVALID_SWITCH_KIND),
        (switch("s", "a", "line", "nope"), ErrorCode.UNKNOWN_SWITCH_TARGET),
        (switch("s", "a", "transformer", "ab"), ErrorCode.UNKNOWN_SWITCH_TARGET),  # a line id
        (switch("s", "a", "bus", "nope"), ErrorCode.UNKNOWN_SWITCH_TARGET),
        (switch("s", "nope", "line", "ab"), ErrorCode.UNKNOWN_BUS_REFERENCE),
        (switch("s", "c", "line", "ab"), ErrorCode.SWITCH_NOT_AT_ELEMENT_TERMINAL),
        (switch("s", "a", "bus", "a"), ErrorCode.SWITCH_CONNECTS_BUS_TO_ITSELF),
    ],
)
def test_invalid_switches(item: Switch, expected: ErrorCode) -> None:
    assert codes(with_switch(three_bus_radial(), item)) == {expected}


def test_a_switch_must_sit_at_a_terminal_of_its_transformer() -> None:
    grid = with_switch(substation_feeder(), switch("s", "b", "transformer", "t1"))
    assert codes(grid) == {ErrorCode.SWITCH_NOT_AT_ELEMENT_TERMINAL}


def test_a_bus_coupler_cannot_join_two_voltage_levels() -> None:
    grid = with_switch(substation_feeder(), switch("s", "hv", "bus", "a"))
    assert codes(grid) == {ErrorCode.SWITCH_VOLTAGE_MISMATCH}


def test_two_switches_cannot_occupy_the_same_place() -> None:
    grid = replace(
        three_bus_radial(),
        switches=(switch("s1", "a", "line", "ab"), switch("s2", "a", "line", "ab", closed=False)),
    )
    assert codes(grid) == {ErrorCode.DUPLICATE_SWITCH}

    other_end = replace(
        three_bus_radial(),
        switches=(switch("s1", "a", "line", "ab"), switch("s2", "b", "line", "ab")),
    )
    assert validate_grid(other_end) == ()


def test_two_couplers_between_the_same_buses_are_duplicates_in_either_direction() -> None:
    radial = three_bus_radial()
    grid = replace(
        radial,
        buses=(*radial.buses, Bus(id="d", name="D", nominal_voltage_kv=20.0)),
        switches=(switch("s1", "c", "bus", "d"), switch("s2", "d", "bus", "c")),
    )
    assert codes(grid) == {ErrorCode.DUPLICATE_SWITCH}


def test_switch_ids_are_checked_like_every_other_id() -> None:
    grid = replace(
        three_bus_radial(),
        switches=(switch("s", "a", "line", "ab"), switch("s", "b", "line", "ab")),
    )
    assert codes(grid) == {ErrorCode.DUPLICATE_ELEMENT_ID}


def test_opening_every_switch_is_an_outage_not_an_error() -> None:
    grid = with_switch(three_bus_radial(), switch("s", "a", "line", "ab", closed=False))
    assert validate_grid(grid) == ()


# --- everything at once ---------------------------------------------------------------


def test_issues_across_all_element_types_are_reported_together() -> None:
    grid = GridModel(
        name="broken",
        frequency_hz=50.0,
        buses=(Bus(id="hv", name="HV", nominal_voltage_kv=110.0),),
        transformers=transformer_feeder(rated_power_mva=0.0).transformers,
        generators=(constant_power_generator("hv", -1.0),),
        switches=(switch("s", "hv", "line", "missing"),),
        external_grids=(ExternalGrid(id="slack", name="Slack", bus_id="hv"),),
    )
    assert codes(grid) == {
        ErrorCode.UNKNOWN_BUS_REFERENCE,  # the transformer's lv bus
        ErrorCode.INVALID_TRANSFORMER_RATED_POWER,
        ErrorCode.NEGATIVE_GENERATOR_ACTIVE_POWER,
        ErrorCode.UNKNOWN_SWITCH_TARGET,
    }
    assert validate_grid(grid) == validate_grid(grid)  # deterministic order
