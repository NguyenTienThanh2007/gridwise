"""Scenarios: deterministic changes to a copy of a grid before it is simulated.

A scenario is an ordered list of modifications. Applying it never touches the stored grid:
it returns a new ``GridModel``, the input of one simulation. The same scenario applied to
the same grid always gives the same model.

Scenario values are study assumptions chosen by the user, not measurements. Setting a
switch in a scenario changes the simulated copy only and reaches no equipment.

Document format ``gridwise.scenario/1``::

    {"schema": "gridwise.scenario/1",
     "modifications": [
        {"type": "scale_loads", "factor": 1.2},
        {"type": "scale_loads", "factor": 1.5, "keys": ["load-r1"]},
        {"type": "scale_generation", "factor": 0.0, "control_mode": "constant_power"},
        {"type": "set_in_service", "element_type": "line", "key": "line-1-2",
         "in_service": false},
        {"type": "set_switch", "key": "switch-1", "closed": true}]}

Pure Python, no numerical library.
"""

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from gridwise_grid_engine.hashing import canonical_json, sha256_hex
from gridwise_grid_engine.model import (
    CONSTANT_POWER,
    GENERATOR_CONTROL_MODES,
    GridModel,
)

SCENARIO_DOCUMENT_SCHEMA = "gridwise.scenario/1"
MAX_MODIFICATIONS = 200
MAX_SCALE_FACTOR = 100.0

#: Element types a scenario may take in or out of service, and the model collection of each.
_IN_SERVICE_GROUPS = {
    "bus": "buses",
    "line": "lines",
    "transformer": "transformers",
    "load": "loads",
    "generator": "generators",
    "external_grid": "external_grids",
}


class ScenarioErrorCode(StrEnum):
    """Stable codes. Documented in docs/domain/grid-engine.md; a test keeps them in step."""

    INVALID_SCENARIO_DOCUMENT = "invalid_scenario_document"
    UNKNOWN_MODIFICATION = "unknown_modification"
    TOO_MANY_MODIFICATIONS = "too_many_modifications"
    INVALID_SCALE_FACTOR = "invalid_scale_factor"
    INVALID_SCENARIO_ELEMENT_TYPE = "invalid_scenario_element_type"
    INVALID_SCENARIO_KEY = "invalid_scenario_key"
    INVALID_SCENARIO_FLAG = "invalid_scenario_flag"
    INVALID_SCENARIO_CONTROL_MODE = "invalid_scenario_control_mode"
    SCENARIO_KEY_NOT_FOUND = "scenario_key_not_found"


@dataclass(frozen=True, slots=True)
class ScenarioIssue:
    code: ScenarioErrorCode
    message: str
    #: Index of the modification, or None for the document as a whole.
    modification: int | None = None


class ScenarioError(ValueError):
    def __init__(self, issues: tuple[ScenarioIssue, ...]) -> None:
        self.issues = issues
        codes = ", ".join(sorted({issue.code.value for issue in issues}))
        super().__init__(f"Scenario is invalid ({len(issues)} issue(s)): {codes}")

    @property
    def codes(self) -> frozenset[ScenarioErrorCode]:
        return frozenset(issue.code for issue in self.issues)


# --- modifications ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ScaleLoads:
    """Multiply ``p_mw`` and ``q_mvar`` of every load, or of the listed loads."""

    factor: float
    keys: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ScaleGeneration:
    """Multiply the active power of every generator, or of the listed ones, optionally only
    those of one control mode. Constant-power units scale their reactive power too."""

    factor: float
    keys: tuple[str, ...] | None = None
    control_mode: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SetInService:
    element_type: str
    key: str
    in_service: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class SetSwitch:
    """The position of a switch in the simulated copy only."""

    key: str
    closed: bool


type Modification = ScaleLoads | ScaleGeneration | SetInService | SetSwitch


@dataclass(frozen=True, slots=True)
class Scenario:
    modifications: tuple[Modification, ...] = ()


# --- documents ----------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_key(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def _parse_keys(raw: object, index: int, issues: list[ScenarioIssue]) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw or not all(_is_key(key) for key in raw):
        issues.append(
            ScenarioIssue(
                ScenarioErrorCode.INVALID_SCENARIO_KEY,
                "keys must be a non-empty list of element keys",
                index,
            )
        )
        return None
    return tuple(raw)


def _parse_factor(
    raw: object, index: int, issues: list[ScenarioIssue], *, allow_zero: bool
) -> float:
    if (
        isinstance(raw, (int, float))
        and not isinstance(raw, bool)
        and math.isfinite(raw)
        and (raw >= 0 if allow_zero else raw > 0)
        and raw <= MAX_SCALE_FACTOR
    ):
        return float(raw)
    bound = "0 <= factor" if allow_zero else "0 < factor"
    issues.append(
        ScenarioIssue(
            ScenarioErrorCode.INVALID_SCALE_FACTOR,
            f"factor must be a finite number with {bound} <= {MAX_SCALE_FACTOR:g}",
            index,
        )
    )
    return 1.0


_FIELDS = {
    "scale_loads": {"type", "factor", "keys"},
    "scale_generation": {"type", "factor", "keys", "control_mode"},
    "set_in_service": {"type", "element_type", "key", "in_service"},
    "set_switch": {"type", "key", "closed"},
}


def _parse_modification(
    raw: object, index: int, issues: list[ScenarioIssue]
) -> Modification | None:
    if not isinstance(raw, dict) or raw.get("type") not in _FIELDS:
        issues.append(
            ScenarioIssue(
                ScenarioErrorCode.UNKNOWN_MODIFICATION,
                "type must be one of: " + ", ".join(_FIELDS),
                index,
            )
        )
        return None
    kind = raw["type"]
    unknown = set(raw) - _FIELDS[kind]
    if unknown:
        issues.append(
            ScenarioIssue(
                ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT,
                f"unknown field(s) for {kind}: " + ", ".join(sorted(unknown)),
                index,
            )
        )
    before = len(issues)

    if kind == "scale_loads":
        factor = _parse_factor(raw.get("factor"), index, issues, allow_zero=False)
        keys = _parse_keys(raw.get("keys"), index, issues)
        result: Modification = ScaleLoads(factor=factor, keys=keys)
    elif kind == "scale_generation":
        factor = _parse_factor(raw.get("factor"), index, issues, allow_zero=True)
        keys = _parse_keys(raw.get("keys"), index, issues)
        mode = raw.get("control_mode")
        if mode is not None and mode not in GENERATOR_CONTROL_MODES:
            issues.append(
                ScenarioIssue(
                    ScenarioErrorCode.INVALID_SCENARIO_CONTROL_MODE,
                    'control_mode must be "constant_power" or "voltage_control"',
                    index,
                )
            )
        result = ScaleGeneration(factor=factor, keys=keys, control_mode=mode)
    elif kind == "set_in_service":
        element_type = raw.get("element_type")
        if element_type not in _IN_SERVICE_GROUPS:
            issues.append(
                ScenarioIssue(
                    ScenarioErrorCode.INVALID_SCENARIO_ELEMENT_TYPE,
                    "element_type must be one of: " + ", ".join(_IN_SERVICE_GROUPS),
                    index,
                )
            )
        if not _is_key(raw.get("key")):
            issues.append(
                ScenarioIssue(ScenarioErrorCode.INVALID_SCENARIO_KEY, "key is required", index)
            )
        if not isinstance(raw.get("in_service"), bool):
            issues.append(
                ScenarioIssue(
                    ScenarioErrorCode.INVALID_SCENARIO_FLAG,
                    "in_service must be true or false",
                    index,
                )
            )
        result = SetInService(
            element_type=str(element_type),
            key=str(raw.get("key")),
            in_service=bool(raw.get("in_service")),
        )
    else:
        if not _is_key(raw.get("key")):
            issues.append(
                ScenarioIssue(ScenarioErrorCode.INVALID_SCENARIO_KEY, "key is required", index)
            )
        if not isinstance(raw.get("closed"), bool):
            issues.append(
                ScenarioIssue(
                    ScenarioErrorCode.INVALID_SCENARIO_FLAG, "closed must be true or false", index
                )
            )
        result = SetSwitch(key=str(raw.get("key")), closed=bool(raw.get("closed")))
    return result if len(issues) == before and not unknown else None


def scenario_from_document(document: object) -> Scenario:
    """Parse and check a scenario document. Every problem is reported at once."""
    issues: list[ScenarioIssue] = []
    if (
        not isinstance(document, dict)
        or document.get("schema") != SCENARIO_DOCUMENT_SCHEMA
        or not isinstance(document.get("modifications"), list)
        or set(document) - {"schema", "modifications"}
    ):
        raise ScenarioError(
            (
                ScenarioIssue(
                    ScenarioErrorCode.INVALID_SCENARIO_DOCUMENT,
                    f'expected {{"schema": "{SCENARIO_DOCUMENT_SCHEMA}", "modifications": [...]}}',
                ),
            )
        )
    raw_modifications = document["modifications"]
    if len(raw_modifications) > MAX_MODIFICATIONS:
        raise ScenarioError(
            (
                ScenarioIssue(
                    ScenarioErrorCode.TOO_MANY_MODIFICATIONS,
                    f"at most {MAX_MODIFICATIONS} modifications",
                ),
            )
        )
    modifications = [
        _parse_modification(raw, index, issues) for index, raw in enumerate(raw_modifications)
    ]
    if issues:
        raise ScenarioError(tuple(issues))
    return Scenario(tuple(item for item in modifications if item is not None))


def scenario_document(scenario: Scenario) -> dict[str, Any]:
    """The canonical document of a scenario. Optional fields that are unset are left out."""
    items: list[dict[str, Any]] = []
    for item in scenario.modifications:
        if isinstance(item, ScaleLoads):
            entry: dict[str, Any] = {"type": "scale_loads", "factor": float(item.factor)}
            if item.keys is not None:
                entry["keys"] = list(item.keys)
        elif isinstance(item, ScaleGeneration):
            entry = {"type": "scale_generation", "factor": float(item.factor)}
            if item.keys is not None:
                entry["keys"] = list(item.keys)
            if item.control_mode is not None:
                entry["control_mode"] = item.control_mode
        elif isinstance(item, SetInService):
            entry = {
                "type": "set_in_service",
                "element_type": item.element_type,
                "key": item.key,
                "in_service": item.in_service,
            }
        else:
            entry = {"type": "set_switch", "key": item.key, "closed": item.closed}
        items.append(entry)
    return {"schema": SCENARIO_DOCUMENT_SCHEMA, "modifications": items}


def scenario_text(scenario: Scenario) -> str:
    return canonical_json(scenario_document(scenario))


def scenario_hash(scenario: Scenario) -> str:
    return sha256_hex(scenario_text(scenario))


# --- applying a scenario ------------------------------------------------------------------


def _missing(
    keys: tuple[str, ...] | None, present: set[str], index: int, what: str
) -> list[ScenarioIssue]:
    return [
        ScenarioIssue(
            ScenarioErrorCode.SCENARIO_KEY_NOT_FOUND, f"the grid has no {what} {key!r}", index
        )
        for key in (keys or ())
        if key not in present
    ]


def apply_scenario(grid: GridModel, scenario: Scenario) -> GridModel:
    """The grid as the scenario describes it. ``grid`` itself is not changed.

    Every key the scenario names must exist in the grid; otherwise nothing is applied and
    every missing key is reported.
    """
    issues: list[ScenarioIssue] = []
    model = grid
    for index, item in enumerate(scenario.modifications):
        if isinstance(item, ScaleLoads):
            issues += _missing(item.keys, {load.id for load in model.loads}, index, "load")
            selected = set(item.keys) if item.keys is not None else None
            model = replace(
                model,
                loads=tuple(
                    replace(load, p_mw=load.p_mw * item.factor, q_mvar=load.q_mvar * item.factor)
                    if selected is None or load.id in selected
                    else load
                    for load in model.loads
                ),
            )
        elif isinstance(item, ScaleGeneration):
            issues += _missing(
                item.keys, {unit.id for unit in model.generators}, index, "generator"
            )
            selected = set(item.keys) if item.keys is not None else None
            units = []
            for unit in model.generators:
                chosen = (selected is None or unit.id in selected) and (
                    item.control_mode is None or unit.control_mode == item.control_mode
                )
                if not chosen:
                    units.append(unit)
                    continue
                q = unit.q_mvar
                if unit.control_mode == CONSTANT_POWER and q is not None:
                    q = q * item.factor
                units.append(replace(unit, p_mw=unit.p_mw * item.factor, q_mvar=q))
            model = replace(model, generators=tuple(units))
        elif isinstance(item, SetInService):
            group = _IN_SERVICE_GROUPS[item.element_type]
            elements = getattr(model, group)
            issues += _missing(
                (item.key,), {element.id for element in elements}, index, item.element_type
            )
            model = replace(
                model,
                **{  # type: ignore[arg-type]
                    group: tuple(
                        replace(element, in_service=item.in_service)
                        if element.id == item.key
                        else element
                        for element in elements
                    )
                },
            )
        else:
            issues += _missing(
                (item.key,), {switch.id for switch in model.switches}, index, "switch"
            )
            model = replace(
                model,
                switches=tuple(
                    replace(switch, closed=item.closed) if switch.id == item.key else switch
                    for switch in model.switches
                ),
            )
    if issues:
        raise ScenarioError(tuple(issues))
    return model


# --- presets: the five study cases of the roadmap -----------------------------------------
#
# Factors are illustrative study assumptions, not measured or forecast values.


def normal_operation() -> Scenario:
    return Scenario()


def demand_increase(factor: float = 1.2) -> Scenario:
    return Scenario((ScaleLoads(factor=factor),))


def transformer_overload(factor: float = 1.6) -> Scenario:
    return Scenario((ScaleLoads(factor=factor),))


def feeder_outage(line_key: str) -> Scenario:
    return Scenario((SetInService(element_type="line", key=line_key, in_service=False),))


def renewable_generation(generation_factor: float = 1.0, load_factor: float = 0.5) -> Scenario:
    """High output of constant-power (inverter-coupled) units at low demand: the case in which
    distributed generation pushes power back up the feeder.

    A generation factor above 1 can exceed a unit's ``rated_power_mva``; the engine then
    refuses the grid instead of simulating an impossible operating point.
    """
    return Scenario(
        (
            ScaleGeneration(factor=generation_factor, control_mode=CONSTANT_POWER),
            ScaleLoads(factor=load_factor),
        )
    )
