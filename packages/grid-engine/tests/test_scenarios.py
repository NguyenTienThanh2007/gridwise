"""Scenarios: parsed strictly, applied deterministically, never changing the original."""

import math
import re
from dataclasses import replace
from pathlib import Path

import pytest
from grid_factories import (
    constant_power_generator,
    switch,
    three_bus_radial,
    voltage_controlled_generator,
)

from gridwise_grid_engine import ErrorCode, GridModel, grid_hash, validate_grid
from gridwise_grid_engine.reference_grids import cigre_mv
from gridwise_grid_engine.scenarios import (
    SCENARIO_DOCUMENT_SCHEMA,
    Scenario,
    ScenarioError,
    ScenarioErrorCode,
    apply_scenario,
    demand_increase,
    feeder_outage,
    normal_operation,
    renewable_generation,
    scenario_document,
    scenario_from_document,
    scenario_hash,
    scenario_text,
    transformer_overload,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def doc(*modifications: object) -> dict[str, object]:
    return {"schema": SCENARIO_DOCUMENT_SCHEMA, "modifications": list(modifications)}


def with_units(grid: GridModel) -> GridModel:
    return replace(
        grid,
        generators=(
            replace(constant_power_generator("c", 0.4, 0.1), id="pv"),
            replace(voltage_controlled_generator("b", 1.0, 1.01), id="chp"),
        ),
        switches=(switch("s-bc", "c", "line", "bc", closed=False),),
    )


GRID = with_units(three_bus_radial())


def apply(*modifications: dict[str, object]) -> GridModel:
    return apply_scenario(GRID, scenario_from_document(doc(*modifications)))


def test_an_empty_scenario_changes_nothing() -> None:
    assert apply() == GRID
    assert apply_scenario(GRID, normal_operation()) == GRID


def test_scale_loads_scales_active_and_reactive_power() -> None:
    result = apply({"type": "scale_loads", "factor": 1.5})
    for before, after in zip(GRID.loads, result.loads, strict=True):
        assert after.p_mw == before.p_mw * 1.5
        assert after.q_mvar == before.q_mvar * 1.5


def test_scale_loads_with_keys_touches_only_those() -> None:
    result = apply({"type": "scale_loads", "factor": 2.0, "keys": ["load-c"]})
    loads = {load.id: load for load in result.loads}
    assert loads["load-b"] == GRID.loads[0]
    assert loads["load-c"].p_mw == 2.0


def test_scale_generation_scales_p_and_constant_power_q_only() -> None:
    result = apply({"type": "scale_generation", "factor": 2.0})
    units = {unit.id: unit for unit in result.generators}
    assert (units["pv"].p_mw, units["pv"].q_mvar) == (0.8, 0.2)
    assert units["chp"].p_mw == 2.0
    assert units["chp"].q_mvar is None  # voltage control: reactive power is a result
    assert units["chp"].voltage_setpoint_pu == 1.01


def test_scale_generation_by_control_mode() -> None:
    result = apply({"type": "scale_generation", "factor": 0.0, "control_mode": "constant_power"})
    units = {unit.id: unit for unit in result.generators}
    assert units["pv"].p_mw == 0.0
    assert units["chp"].p_mw == 1.0


@pytest.mark.parametrize(
    ("element_type", "key", "group"),
    [
        ("bus", "c", "buses"),
        ("line", "bc", "lines"),
        ("load", "load-b", "loads"),
        ("generator", "pv", "generators"),
        ("external_grid", "slack", "external_grids"),
    ],
)
def test_set_in_service(element_type: str, key: str, group: str) -> None:
    result = apply(
        {"type": "set_in_service", "element_type": element_type, "key": key, "in_service": False}
    )
    changed = {element.id: element for element in getattr(result, group)}
    assert changed[key].in_service is False
    others = [element for element in getattr(result, group) if element.id != key]
    assert others == [element for element in getattr(GRID, group) if element.id != key]


def test_set_switch_changes_the_simulated_copy_only() -> None:
    result = apply({"type": "set_switch", "key": "s-bc", "closed": True})
    assert result.switches[0].closed is True
    assert GRID.switches[0].closed is False  # the original is untouched


def test_modifications_apply_in_order() -> None:
    result = apply(
        {"type": "scale_loads", "factor": 2.0},
        {"type": "scale_loads", "factor": 1.5, "keys": ["load-b"]},
    )
    loads = {load.id: load for load in result.loads}
    assert loads["load-b"].p_mw == 2.0 * 2.0 * 1.5
    assert loads["load-c"].p_mw == 1.0 * 2.0


def test_applying_is_deterministic() -> None:
    scenario = scenario_from_document(
        doc(
            {"type": "scale_loads", "factor": 1.2},
            {"type": "set_switch", "key": "s-bc", "closed": True},
        )
    )
    assert grid_hash(apply_scenario(GRID, scenario)) == grid_hash(apply_scenario(GRID, scenario))


def test_missing_keys_are_all_reported_and_nothing_is_applied() -> None:
    scenario = scenario_from_document(
        doc(
            {"type": "scale_loads", "factor": 2.0, "keys": ["load-b", "nope"]},
            {"type": "set_in_service", "element_type": "line", "key": "gone", "in_service": False},
            {"type": "set_switch", "key": "missing", "closed": True},
        )
    )
    with pytest.raises(ScenarioError) as raised:
        apply_scenario(GRID, scenario)
    assert raised.value.codes == {ScenarioErrorCode.SCENARIO_KEY_NOT_FOUND}
    assert [issue.modification for issue in raised.value.issues] == [0, 1, 2]


def test_a_scenario_can_make_a_grid_invalid_and_validation_says_so() -> None:
    result = apply(
        {
            "type": "set_in_service",
            "element_type": "external_grid",
            "key": "slack",
            "in_service": False,
        }
    )
    assert {issue.code for issue in validate_grid(result)} == {ErrorCode.MISSING_EXTERNAL_GRID}


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"modifications": []}, ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT),
        ({"schema": "other", "modifications": []}, ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT),
        ({**doc(), "extra": 1}, ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT),
        ("not a dict", ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT),
        (doc({"type": "explode"}), ScenarioErrorCode.UNKNOWN_MODIFICATION),
        (doc("x"), ScenarioErrorCode.UNKNOWN_MODIFICATION),
        (doc({"type": "scale_loads", "factor": 0}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (doc({"type": "scale_loads", "factor": -1}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (doc({"type": "scale_loads", "factor": 101}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (doc({"type": "scale_loads", "factor": math.nan}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (doc({"type": "scale_loads", "factor": "2"}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (doc({"type": "scale_loads", "factor": True}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (doc({"type": "scale_generation", "factor": -0.1}), ScenarioErrorCode.INVALID_SCALE_FACTOR),
        (
            doc({"type": "scale_loads", "factor": 1, "keys": []}),
            ScenarioErrorCode.INVALID_SCENARIO_KEY,
        ),
        (
            doc({"type": "scale_loads", "factor": 1, "keys": [""]}),
            ScenarioErrorCode.INVALID_SCENARIO_KEY,
        ),
        (
            doc({"type": "scale_loads", "factor": 1, "keys": "load-b"}),
            ScenarioErrorCode.INVALID_SCENARIO_KEY,
        ),
        (
            doc({"type": "scale_generation", "factor": 1, "control_mode": "droop"}),
            ScenarioErrorCode.INVALID_SCENARIO_CONTROL_MODE,
        ),
        (
            doc(
                {
                    "type": "set_in_service",
                    "element_type": "switch",
                    "key": "s",
                    "in_service": False,
                }
            ),
            ScenarioErrorCode.INVALID_SCENARIO_ELEMENT_TYPE,
        ),
        (
            doc(
                {"type": "set_in_service", "element_type": "line", "key": "ab", "in_service": "no"}
            ),
            ScenarioErrorCode.INVALID_SCENARIO_FLAG,
        ),
        (
            doc({"type": "set_switch", "key": "s", "closed": 1}),
            ScenarioErrorCode.INVALID_SCENARIO_FLAG,
        ),
        (doc({"type": "set_switch", "closed": True}), ScenarioErrorCode.INVALID_SCENARIO_KEY),
        (
            doc({"type": "set_switch", "key": "s", "closed": True, "force": True}),
            ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT,
        ),
        (
            {
                "schema": SCENARIO_DOCUMENT_SCHEMA,
                "modifications": [{"type": "scale_loads", "factor": 1}] * 201,
            },
            ScenarioErrorCode.TOO_MANY_MODIFICATIONS,
        ),
    ],
)
def test_invalid_documents_are_refused(document: object, code: ScenarioErrorCode) -> None:
    with pytest.raises(ScenarioError) as raised:
        scenario_from_document(document)
    assert code in raised.value.codes


def test_every_issue_of_a_document_is_reported_at_once() -> None:
    with pytest.raises(ScenarioError) as raised:
        scenario_from_document(
            doc(
                {"type": "scale_loads", "factor": 0},
                {"type": "set_switch", "key": "", "closed": "x"},
            )
        )
    assert raised.value.codes == {
        ScenarioErrorCode.INVALID_SCALE_FACTOR,
        ScenarioErrorCode.INVALID_SCENARIO_KEY,
        ScenarioErrorCode.INVALID_SCENARIO_FLAG,
    }


def test_a_document_round_trips_canonically() -> None:
    document = doc(
        {"type": "scale_loads", "factor": 2, "keys": ["load-b"]},
        {"type": "scale_generation", "factor": 0.5, "control_mode": "constant_power"},
        {"type": "set_in_service", "element_type": "line", "key": "ab", "in_service": False},
        {"type": "set_switch", "key": "s-bc", "closed": True},
    )
    scenario = scenario_from_document(document)
    assert scenario_from_document(scenario_document(scenario)) == scenario
    assert scenario_document(scenario)["modifications"][0]["factor"] == 2.0
    assert scenario_hash(scenario) == scenario_hash(
        scenario_from_document(scenario_document(scenario))
    )
    assert scenario_text(scenario).startswith('{"modifications":')


def test_different_scenarios_have_different_hashes() -> None:
    assert scenario_hash(demand_increase(1.2)) != scenario_hash(demand_increase(1.21))
    assert scenario_hash(Scenario()) != scenario_hash(demand_increase())


def test_the_presets_apply_to_the_benchmark_and_stay_valid() -> None:
    grid = cigre_mv.cigre_mv_with_der()
    for scenario in (
        normal_operation(),
        demand_increase(),
        transformer_overload(),
        feeder_outage("line-1-2"),
        renewable_generation(),
    ):
        assert validate_grid(apply_scenario(grid, scenario)) == ()


def test_scaling_generation_beyond_its_rating_makes_the_grid_invalid() -> None:
    """The scenario is applied as asked; the engine's validation then refuses the result."""
    grid = apply_scenario(cigre_mv.cigre_mv_with_der(), renewable_generation(generation_factor=2.0))
    assert ErrorCode.GENERATOR_EXCEEDS_RATED_POWER in {issue.code for issue in validate_grid(grid)}


def test_every_scenario_error_code_is_documented() -> None:
    text = (REPO_ROOT / "docs/domain/grid-engine.md").read_text()
    table = text.split("## Scenario error codes", 1)[1].split("\n## ", 1)[0]
    documented = set(re.findall(r"^\| `([a-z_]+)`", table, flags=re.MULTILINE))
    assert documented == {code.value for code in ScenarioErrorCode}
