import math
import re
from dataclasses import replace
from pathlib import Path

import pytest
from grid_factories import three_bus_radial, two_bus, with_bus, with_line

from gridwise_grid_engine import (
    Bus,
    ErrorCode,
    ExternalGrid,
    GridModel,
    GridValidationError,
    Load,
    PowerFlowOptions,
    RawSolution,
    run_power_flow,
    validate_grid,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def codes(grid: GridModel) -> set[ErrorCode]:
    return {issue.code for issue in validate_grid(grid)}


def with_slack(grid: GridModel, **changes: object) -> GridModel:
    return replace(
        grid,
        external_grids=tuple(replace(s, **changes) for s in grid.external_grids),  # type: ignore[arg-type]
    )


def with_load(grid: GridModel, **changes: object) -> GridModel:
    return replace(grid, loads=tuple(replace(load, **changes) for load in grid.loads))  # type: ignore[arg-type]


class CountingSolver:
    name = "counting"
    version = "0"

    def __init__(self) -> None:
        self.calls = 0

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        self.calls += 1
        return RawSolution(converged=False)


def test_the_test_grids_are_valid() -> None:
    assert validate_grid(two_bus()) == ()
    assert validate_grid(three_bus_radial()) == ()


# --- missing slack --------------------------------------------------------------------


def test_missing_external_grid() -> None:
    grid = replace(two_bus(), external_grids=())
    (issue,) = validate_grid(grid)
    assert issue.code is ErrorCode.MISSING_EXTERNAL_GRID
    assert issue.element_type == "grid"


def test_an_out_of_service_external_grid_is_not_a_slack() -> None:
    assert codes(with_slack(two_bus(), in_service=False)) == {ErrorCode.MISSING_EXTERNAL_GRID}


def test_an_external_grid_on_an_out_of_service_bus_is_not_a_slack() -> None:
    grid = with_bus(two_bus(), "source", in_service=False)
    assert codes(grid) == {ErrorCode.MISSING_EXTERNAL_GRID}


def test_two_external_grids_on_one_bus_are_rejected() -> None:
    grid = two_bus()
    extra = ExternalGrid(id="slack-2", name="Second", bus_id="source")
    assert codes(replace(grid, external_grids=(*grid.external_grids, extra))) == {
        ErrorCode.MULTIPLE_EXTERNAL_GRIDS_ON_BUS
    }


# --- lines ----------------------------------------------------------------------------


@pytest.mark.parametrize("length_km", [0.0, -1.0])
def test_zero_or_negative_line_length(length_km: float) -> None:
    (issue,) = validate_grid(with_line(two_bus(), "line", length_km=length_km))
    assert issue.code is ErrorCode.INVALID_LINE_LENGTH
    assert (issue.element_type, issue.element_id, issue.field) == ("line", "line", "length_km")


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"r_ohm_per_km": -0.1}, ErrorCode.NEGATIVE_LINE_RESISTANCE),
        ({"x_ohm_per_km": -0.1}, ErrorCode.NEGATIVE_LINE_REACTANCE),
        ({"r_ohm_per_km": 0.0, "x_ohm_per_km": 0.0}, ErrorCode.ZERO_LINE_IMPEDANCE),
        ({"c_nf_per_km": -1.0}, ErrorCode.NEGATIVE_LINE_CAPACITANCE),
        ({"max_i_ka": 0.0}, ErrorCode.INVALID_LINE_THERMAL_LIMIT),
        ({"max_i_ka": -0.2}, ErrorCode.INVALID_LINE_THERMAL_LIMIT),
        ({"to_bus_id": "nowhere"}, ErrorCode.UNKNOWN_BUS_REFERENCE),
        ({"from_bus_id": "nowhere"}, ErrorCode.UNKNOWN_BUS_REFERENCE),
        ({"to_bus_id": "source"}, ErrorCode.LINE_CONNECTS_BUS_TO_ITSELF),
    ],
)
def test_invalid_line_parameters(changes: dict[str, object], expected: ErrorCode) -> None:
    assert codes(with_line(two_bus(), "line", **changes)) == {expected}


def test_a_resistive_only_or_reactive_only_line_is_allowed() -> None:
    assert validate_grid(with_line(two_bus(), "line", x_ohm_per_km=0.0)) == ()
    assert validate_grid(with_line(two_bus(), "line", r_ohm_per_km=0.0)) == ()


def test_a_line_cannot_join_two_voltage_levels() -> None:
    grid = with_bus(two_bus(), "load", nominal_voltage_kv=10.0)
    (issue,) = validate_grid(grid)
    assert issue.code is ErrorCode.LINE_VOLTAGE_MISMATCH
    assert "transformer" in issue.message


# --- voltages -------------------------------------------------------------------------


@pytest.mark.parametrize("voltage", [0.0, -20.0])
def test_non_positive_nominal_voltage(voltage: float) -> None:
    grid = replace(
        two_bus(),
        buses=tuple(replace(bus, nominal_voltage_kv=voltage) for bus in two_bus().buses),
    )
    assert codes(grid) == {ErrorCode.INVALID_NOMINAL_VOLTAGE}
    assert len(validate_grid(grid)) == 2  # one per bus


@pytest.mark.parametrize("voltage", [0.0, -1.0])
def test_non_positive_external_grid_voltage(voltage: float) -> None:
    assert codes(with_slack(two_bus(), voltage_pu=voltage)) == {
        ErrorCode.INVALID_EXTERNAL_GRID_VOLTAGE
    }


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, "20", None, True])
def test_values_that_are_not_finite_real_numbers(bad: object) -> None:
    by_bus = with_bus(two_bus(), "load", nominal_voltage_kv=bad)
    assert ErrorCode.INVALID_NUMBER in codes(by_bus)
    assert ErrorCode.INVALID_NOMINAL_VOLTAGE not in codes(by_bus)  # no range check on junk

    assert codes(with_line(two_bus(), "line", length_km=bad)) == {ErrorCode.INVALID_NUMBER}
    assert codes(with_load(two_bus(), q_mvar=bad)) == {ErrorCode.INVALID_NUMBER}
    assert codes(with_slack(two_bus(), voltage_angle_degree=bad)) == {ErrorCode.INVALID_NUMBER}


# --- in-service flags -----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["false", "true", None, 0, 1, 0.0, [], "no"])
def test_in_service_must_be_a_real_boolean(bad: object) -> None:
    """The string "false" is truthy; accepting it would energise a switched-off element."""
    for grid in (
        with_bus(two_bus(), "load", in_service=bad),
        with_line(two_bus(), "line", in_service=bad),
        with_load(two_bus(), in_service=bad),
    ):
        (issue,) = validate_grid(grid)
        assert issue.code is ErrorCode.INVALID_IN_SERVICE_FLAG
        assert issue.field == "in_service"

    # On the only source, a falsy junk value also leaves the grid without a slack.
    assert ErrorCode.INVALID_IN_SERVICE_FLAG in codes(with_slack(two_bus(), in_service=bad))


def test_an_invalid_in_service_flag_never_reaches_the_solver() -> None:
    solver = CountingSolver()
    with pytest.raises(GridValidationError) as raised:
        run_power_flow(with_line(two_bus(), "line", in_service="false"), solver)
    assert solver.calls == 0
    assert raised.value.codes == {ErrorCode.INVALID_IN_SERVICE_FLAG}


@pytest.mark.parametrize("flag", [True, False])
def test_real_booleans_are_accepted(flag: bool) -> None:
    assert ErrorCode.INVALID_IN_SERVICE_FLAG not in codes(with_load(two_bus(), in_service=flag))


# --- grid, loads, identifiers ---------------------------------------------------------


@pytest.mark.parametrize("frequency", [0.0, 16.7, 55.0, 400.0])
def test_unsupported_frequency(frequency: float) -> None:
    assert codes(replace(two_bus(), frequency_hz=frequency)) == {ErrorCode.INVALID_FREQUENCY}


def test_both_supported_frequencies_are_accepted() -> None:
    assert validate_grid(two_bus(frequency_hz=50)) == ()  # an int is fine
    assert validate_grid(two_bus(frequency_hz=60.0)) == ()


def test_a_grid_without_buses() -> None:
    grid = GridModel(name="empty", frequency_hz=50.0, buses=())
    assert codes(grid) == {ErrorCode.NO_BUSES, ErrorCode.MISSING_EXTERNAL_GRID}


def test_negative_load_active_power_is_not_generation() -> None:
    (issue,) = validate_grid(with_load(two_bus(), p_mw=-1.0))
    assert issue.code is ErrorCode.NEGATIVE_LOAD_ACTIVE_POWER


def test_reactive_power_may_have_either_sign() -> None:
    assert validate_grid(with_load(two_bus(), q_mvar=-0.8)) == ()


def test_load_on_an_unknown_bus() -> None:
    assert codes(with_load(two_bus(), bus_id="nowhere")) == {ErrorCode.UNKNOWN_BUS_REFERENCE}


def test_duplicate_and_empty_identifiers() -> None:
    grid = two_bus()
    duplicate = replace(
        grid, buses=(*grid.buses, Bus(id="load", name="Again", nominal_voltage_kv=20.0))
    )
    assert codes(duplicate) == {ErrorCode.DUPLICATE_ELEMENT_ID}

    blank = replace(grid, loads=(Load(id="  ", name="Blank", bus_id="load", p_mw=1.0, q_mvar=0.0),))
    assert codes(blank) == {ErrorCode.INVALID_IDENTIFIER}


def test_the_same_id_may_be_used_by_elements_of_different_types() -> None:
    grid = two_bus()
    reused = replace(grid, loads=(replace(grid.loads[0], id="line"),))
    assert validate_grid(reused) == ()


# --- behaviour ------------------------------------------------------------------------


def test_every_issue_is_reported_at_once_in_a_stable_order() -> None:
    grid = with_line(
        replace(two_bus(p_mw=-1.0), external_grids=(), frequency_hz=55.0),
        "line",
        length_km=0.0,
        max_i_ka=-1.0,
    )
    expected = {
        ErrorCode.INVALID_FREQUENCY,
        ErrorCode.INVALID_LINE_LENGTH,
        ErrorCode.INVALID_LINE_THERMAL_LIMIT,
        ErrorCode.NEGATIVE_LOAD_ACTIVE_POWER,
        ErrorCode.MISSING_EXTERNAL_GRID,
    }
    assert codes(grid) == expected
    assert validate_grid(grid) == validate_grid(grid)


def test_an_invalid_grid_is_never_handed_to_the_solver() -> None:
    solver = CountingSolver()
    with pytest.raises(GridValidationError) as raised:
        run_power_flow(with_line(two_bus(), "line", length_km=0.0), solver)
    assert solver.calls == 0
    assert raised.value.codes == {ErrorCode.INVALID_LINE_LENGTH}
    assert "invalid_line_length" in str(raised.value)


def test_outages_are_valid_inputs_not_errors() -> None:
    assert validate_grid(with_line(three_bus_radial(), "bc", in_service=False)) == ()
    assert validate_grid(with_bus(three_bus_radial(), "c", in_service=False)) == ()


def test_models_are_immutable_and_accept_any_iterable() -> None:
    grid = GridModel(
        name="lists",
        frequency_hz=50.0,
        buses=[Bus(id="a", name="A", nominal_voltage_kv=20.0)],  # type: ignore[arg-type]
    )
    assert isinstance(grid.buses, tuple)
    with pytest.raises(AttributeError):
        grid.buses[0].nominal_voltage_kv = 10.0  # type: ignore[misc]


def test_every_error_code_is_documented_and_no_documented_code_is_stale() -> None:
    text = (REPO_ROOT / "docs/domain/grid-engine.md").read_text()
    table = text.split("## Error codes", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `([a-z_]+)`", table, flags=re.MULTILINE))
    assert documented == {code.value for code in ErrorCode}


def test_error_code_values_are_frozen() -> None:
    """Renaming a code is a breaking change. Additions are appended here deliberately."""
    assert sorted(code.value for code in ErrorCode) == [
        "duplicate_element_id",
        "inconsistent_solution",
        "invalid_external_grid_voltage",
        "invalid_frequency",
        "invalid_identifier",
        "invalid_in_service_flag",
        "invalid_line_length",
        "invalid_line_thermal_limit",
        "invalid_nominal_voltage",
        "invalid_number",
        "line_connects_bus_to_itself",
        "line_voltage_mismatch",
        "missing_external_grid",
        "multiple_external_grids_on_bus",
        "negative_line_capacitance",
        "negative_line_reactance",
        "negative_line_resistance",
        "negative_load_active_power",
        "no_buses",
        "power_flow_not_converged",
        "solver_failed",
        "unknown_bus_reference",
        "zero_line_impedance",
    ]
