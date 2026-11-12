"""Electrical and topological validation.

Finds every problem in one pass and reports each with a stable ``ErrorCode``. Nothing here
depends on a solver: a grid that passes can be handed to any ``PowerFlowSolver``.

Deliberately *not* errors: out-of-service elements, and in-service buses that no external
grid can reach. Those are legitimate network states (an outage); the engine reports such
buses as de-energised rather than refusing to solve.
"""

import math
from collections import Counter
from collections.abc import Iterable

from gridwise_grid_engine.errors import ErrorCode, GridValidationError, ValidationIssue
from gridwise_grid_engine.model import (
    CONSTANT_POWER,
    GENERATOR_CONTROL_MODES,
    SWITCH_ELEMENT_TYPES,
    SWITCH_KINDS,
    TAP_SIDES,
    VOLTAGE_CONTROL,
    Bus,
    ExternalGrid,
    Generator,
    GridModel,
    Line,
    Load,
    Switch,
    Transformer,
)

SUPPORTED_FREQUENCIES_HZ = (50.0, 60.0)

#: Fields that must be finite real numbers. Optional fields are checked when not None.
_NUMERIC_FIELDS: dict[type, tuple[str, ...]] = {
    Bus: ("nominal_voltage_kv",),
    Line: ("length_km", "r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka"),
    Load: ("p_mw", "q_mvar"),
    ExternalGrid: ("voltage_pu", "voltage_angle_degree"),
    Transformer: (
        "rated_power_mva",
        "rated_voltage_hv_kv",
        "rated_voltage_lv_kv",
        "short_circuit_voltage_percent",
        "short_circuit_resistive_percent",
        "iron_losses_kw",
        "no_load_current_percent",
        "phase_shift_degree",
    ),
    Generator: ("p_mw",),
    Switch: (),
}
_OPTIONAL_NUMERIC_FIELDS: dict[type, tuple[str, ...]] = {
    Generator: ("q_mvar", "voltage_setpoint_pu", "min_q_mvar", "max_q_mvar", "rated_power_mva"),
}
_ELEMENT_TYPE = {
    Bus: "bus",
    Line: "line",
    Load: "load",
    ExternalGrid: "external_grid",
    Transformer: "transformer",
    Generator: "generator",
    Switch: "switch",
}

type Element = Bus | Line | Load | ExternalGrid | Transformer | Generator | Switch

#: Slack allowed when comparing a generator's apparent power with its rating, and a
#: transformer's no-load current with what its iron losses require (rounded nameplate data).
_RELATIVE_SLACK = 1e-9


def _is_real_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class _Collector:
    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def add(
        self,
        code: ErrorCode,
        message: str,
        element: Element | None = None,
        field: str | None = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                code=code,
                message=message,
                element_type=_ELEMENT_TYPE[type(element)] if element is not None else "grid",
                element_id=element.id if element is not None else None,
                field=field,
            )
        )


def _check_identifiers(out: _Collector, elements: Iterable[Element]) -> None:
    items = list(elements)
    for element in items:
        if not isinstance(element.id, str) or not element.id.strip():
            out.add(ErrorCode.INVALID_IDENTIFIER, "Element id must be a non-empty string", element)
    counts = Counter(element.id for element in items if isinstance(element.id, str))
    seen: set[str] = set()
    for element in items:
        if isinstance(element.id, str) and counts[element.id] > 1 and element.id not in seen:
            seen.add(element.id)
            out.add(
                ErrorCode.DUPLICATE_ELEMENT_ID,
                f"{counts[element.id]} {_ELEMENT_TYPE[type(element)]} elements share this id",
                element,
            )


def _check_in_service_flag(out: _Collector, element: Element) -> None:
    """``in_service`` decides what is energised, so "truthy" is not good enough.

    Without this, the string ``"false"`` would silently count as in service.
    """
    if isinstance(element, Switch):
        return  # a switch has a position (``closed``), checked in _check_switch
    if not isinstance(element.in_service, bool):
        out.add(
            ErrorCode.INVALID_IN_SERVICE_FLAG,
            "in_service must be true or false",
            element,
            "in_service",
        )


def _numbers_are_valid(out: _Collector, element: Element) -> bool:
    """Report non-numeric or non-finite fields. Range checks only run when this passes."""
    valid = True
    for name in _NUMERIC_FIELDS[type(element)]:
        if not _is_real_number(getattr(element, name)):
            out.add(ErrorCode.INVALID_NUMBER, f"{name} must be a finite real number", element, name)
            valid = False
    for name in _OPTIONAL_NUMERIC_FIELDS.get(type(element), ()):
        value = getattr(element, name)
        if value is not None and not _is_real_number(value):
            out.add(
                ErrorCode.INVALID_NUMBER,
                f"{name} must be a finite real number when given",
                element,
                name,
            )
            valid = False
    return valid


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_bus(out: _Collector, bus: Bus) -> None:
    if _numbers_are_valid(out, bus) and bus.nominal_voltage_kv <= 0:
        out.add(
            ErrorCode.INVALID_NOMINAL_VOLTAGE,
            "nominal_voltage_kv must be greater than 0",
            bus,
            "nominal_voltage_kv",
        )


def _check_line(out: _Collector, line: Line, buses: dict[str, Bus]) -> None:
    ends = {"from_bus_id": line.from_bus_id, "to_bus_id": line.to_bus_id}
    for name, bus_id in ends.items():
        if bus_id not in buses:
            out.add(ErrorCode.UNKNOWN_BUS_REFERENCE, f"{name} refers to no bus", line, name)

    if line.from_bus_id == line.to_bus_id:
        out.add(
            ErrorCode.LINE_CONNECTS_BUS_TO_ITSELF,
            "from_bus_id and to_bus_id must be different buses",
            line,
        )
    elif all(bus_id in buses for bus_id in ends.values()):
        from_kv = buses[line.from_bus_id].nominal_voltage_kv
        to_kv = buses[line.to_bus_id].nominal_voltage_kv
        if (
            _is_real_number(from_kv)
            and _is_real_number(to_kv)
            and not math.isclose(from_kv, to_kv, rel_tol=1e-9, abs_tol=0.0)
        ):
            out.add(
                ErrorCode.LINE_VOLTAGE_MISMATCH,
                "A line must join buses of the same nominal voltage; "
                "different voltage levels need a transformer",
                line,
            )

    if not _numbers_are_valid(out, line):
        return
    if line.length_km <= 0:
        out.add(
            ErrorCode.INVALID_LINE_LENGTH, "length_km must be greater than 0", line, "length_km"
        )
    if line.r_ohm_per_km < 0:
        out.add(
            ErrorCode.NEGATIVE_LINE_RESISTANCE,
            "r_ohm_per_km must not be negative",
            line,
            "r_ohm_per_km",
        )
    if line.x_ohm_per_km < 0:
        out.add(
            ErrorCode.NEGATIVE_LINE_REACTANCE,
            "x_ohm_per_km must not be negative",
            line,
            "x_ohm_per_km",
        )
    if line.r_ohm_per_km == 0 and line.x_ohm_per_km == 0:
        out.add(
            ErrorCode.ZERO_LINE_IMPEDANCE,
            "r_ohm_per_km and x_ohm_per_km must not both be 0",
            line,
        )
    if line.c_nf_per_km < 0:
        out.add(
            ErrorCode.NEGATIVE_LINE_CAPACITANCE,
            "c_nf_per_km must not be negative",
            line,
            "c_nf_per_km",
        )
    if line.max_i_ka <= 0:
        out.add(
            ErrorCode.INVALID_LINE_THERMAL_LIMIT,
            "max_i_ka must be greater than 0",
            line,
            "max_i_ka",
        )


def _check_load(out: _Collector, load: Load, buses: dict[str, Bus]) -> None:
    if load.bus_id not in buses:
        out.add(ErrorCode.UNKNOWN_BUS_REFERENCE, "bus_id refers to no bus", load, "bus_id")
    if _numbers_are_valid(out, load) and load.p_mw < 0:
        out.add(
            ErrorCode.NEGATIVE_LOAD_ACTIVE_POWER,
            "p_mw must not be negative; generation is not a load",
            load,
            "p_mw",
        )


def _check_external_grid(out: _Collector, source: ExternalGrid, buses: dict[str, Bus]) -> None:
    if source.bus_id not in buses:
        out.add(ErrorCode.UNKNOWN_BUS_REFERENCE, "bus_id refers to no bus", source, "bus_id")
    if _numbers_are_valid(out, source) and source.voltage_pu <= 0:
        out.add(
            ErrorCode.INVALID_EXTERNAL_GRID_VOLTAGE,
            "voltage_pu must be greater than 0",
            source,
            "voltage_pu",
        )


def _check_tap_changer(out: _Collector, transformer: Transformer) -> None:
    tap = transformer.tap
    if tap is None:
        return

    def invalid(message: str, field: str) -> None:
        out.add(ErrorCode.INVALID_TAP_CHANGER, message, transformer, f"tap.{field}")

    if tap.side not in TAP_SIDES:
        invalid('side must be "hv" or "lv"', "side")
    positions = {
        "neutral_position": tap.neutral_position,
        "min_position": tap.min_position,
        "max_position": tap.max_position,
        "position": tap.position,
    }
    integers = True
    for name, value in positions.items():
        if not _is_integer(value):
            invalid(f"{name} must be an integer", name)
            integers = False
    if not _is_real_number(tap.step_percent):
        invalid("step_percent must be a finite real number", "step_percent")
    elif tap.step_percent <= 0:
        invalid("step_percent must be greater than 0", "step_percent")
    if not integers:
        return
    if tap.min_position > tap.max_position:
        invalid("min_position must not exceed max_position", "min_position")
        return
    if not tap.min_position <= tap.neutral_position <= tap.max_position:
        invalid(
            "neutral_position must lie between min_position and max_position", "neutral_position"
        )
    if not tap.min_position <= tap.position <= tap.max_position:
        invalid("position must lie between min_position and max_position", "position")


def _check_transformer(out: _Collector, transformer: Transformer, buses: dict[str, Bus]) -> None:
    ends = {"hv_bus_id": transformer.hv_bus_id, "lv_bus_id": transformer.lv_bus_id}
    for name, bus_id in ends.items():
        if bus_id not in buses:
            out.add(ErrorCode.UNKNOWN_BUS_REFERENCE, f"{name} refers to no bus", transformer, name)

    if transformer.hv_bus_id == transformer.lv_bus_id:
        out.add(
            ErrorCode.TRANSFORMER_CONNECTS_BUS_TO_ITSELF,
            "hv_bus_id and lv_bus_id must be different buses",
            transformer,
        )
    elif all(bus_id in buses for bus_id in ends.values()):
        hv_kv = buses[transformer.hv_bus_id].nominal_voltage_kv
        lv_kv = buses[transformer.lv_bus_id].nominal_voltage_kv
        if _is_real_number(hv_kv) and _is_real_number(lv_kv) and not hv_kv > lv_kv:
            out.add(
                ErrorCode.TRANSFORMER_VOLTAGE_MISMATCH,
                "The bus at hv_bus_id must have a higher nominal voltage than the bus at lv_bus_id",
                transformer,
            )

    _check_tap_changer(out, transformer)

    if not _numbers_are_valid(out, transformer):
        return
    if transformer.rated_power_mva <= 0:
        out.add(
            ErrorCode.INVALID_TRANSFORMER_RATED_POWER,
            "rated_power_mva must be greater than 0",
            transformer,
            "rated_power_mva",
        )
    if transformer.rated_voltage_lv_kv <= 0:
        out.add(
            ErrorCode.INVALID_TRANSFORMER_RATED_VOLTAGE,
            "rated_voltage_lv_kv must be greater than 0",
            transformer,
            "rated_voltage_lv_kv",
        )
    if transformer.rated_voltage_hv_kv <= transformer.rated_voltage_lv_kv:
        out.add(
            ErrorCode.INVALID_TRANSFORMER_RATED_VOLTAGE,
            "rated_voltage_hv_kv must be greater than rated_voltage_lv_kv",
            transformer,
            "rated_voltage_hv_kv",
        )
    if transformer.short_circuit_voltage_percent <= 0:
        out.add(
            ErrorCode.INVALID_TRANSFORMER_SHORT_CIRCUIT_VOLTAGE,
            "short_circuit_voltage_percent must be greater than 0",
            transformer,
            "short_circuit_voltage_percent",
        )
    if (
        not 0
        <= transformer.short_circuit_resistive_percent
        <= max(transformer.short_circuit_voltage_percent, 0.0)
    ):
        out.add(
            ErrorCode.INVALID_TRANSFORMER_SHORT_CIRCUIT_VOLTAGE,
            "short_circuit_resistive_percent must lie between 0 and short_circuit_voltage_percent",
            transformer,
            "short_circuit_resistive_percent",
        )
    if transformer.iron_losses_kw < 0:
        out.add(
            ErrorCode.NEGATIVE_TRANSFORMER_IRON_LOSSES,
            "iron_losses_kw must not be negative",
            transformer,
            "iron_losses_kw",
        )
    if transformer.no_load_current_percent < 0:
        out.add(
            ErrorCode.INVALID_TRANSFORMER_NO_LOAD_CURRENT,
            "no_load_current_percent must not be negative",
            transformer,
            "no_load_current_percent",
        )
    elif transformer.rated_power_mva > 0 and transformer.iron_losses_kw >= 0:
        # The no-load apparent power (i0 * S_rated) cannot be smaller than its active part
        # (the iron losses). A solver would otherwise quietly drop the magnetising current.
        required_percent = transformer.iron_losses_kw / (transformer.rated_power_mva * 10.0)
        if transformer.no_load_current_percent < required_percent * (1 - _RELATIVE_SLACK):
            out.add(
                ErrorCode.INVALID_TRANSFORMER_NO_LOAD_CURRENT,
                "no_load_current_percent is smaller than the iron losses alone require "
                "(iron_losses_kw / (10 * rated_power_mva))",
                transformer,
                "no_load_current_percent",
            )


def _check_generator(out: _Collector, generator: Generator, buses: dict[str, Bus]) -> None:
    if generator.bus_id not in buses:
        out.add(ErrorCode.UNKNOWN_BUS_REFERENCE, "bus_id refers to no bus", generator, "bus_id")

    mode = generator.control_mode
    if mode not in GENERATOR_CONTROL_MODES:
        out.add(
            ErrorCode.INVALID_GENERATOR_CONTROL_MODE,
            'control_mode must be "constant_power" or "voltage_control"',
            generator,
            "control_mode",
        )

    def wrong(message: str, field: str) -> None:
        out.add(ErrorCode.INVALID_GENERATOR_PARAMETERS, message, generator, field)

    if mode == CONSTANT_POWER:
        if generator.q_mvar is None:
            wrong("q_mvar is required in constant_power mode", "q_mvar")
        for name in ("voltage_setpoint_pu", "min_q_mvar", "max_q_mvar"):
            if getattr(generator, name) is not None:
                wrong(f"{name} applies to voltage_control mode only", name)
    elif mode == VOLTAGE_CONTROL:
        if generator.voltage_setpoint_pu is None:
            wrong("voltage_setpoint_pu is required in voltage_control mode", "voltage_setpoint_pu")
        if generator.q_mvar is not None:
            wrong("q_mvar applies to constant_power mode only", "q_mvar")
        if (generator.min_q_mvar is None) != (generator.max_q_mvar is None):
            out.add(
                ErrorCode.INVALID_GENERATOR_REACTIVE_LIMITS,
                "min_q_mvar and max_q_mvar must be given together or not at all",
                generator,
            )

    if not _numbers_are_valid(out, generator):
        return
    if generator.p_mw < 0:
        out.add(
            ErrorCode.NEGATIVE_GENERATOR_ACTIVE_POWER,
            "p_mw must not be negative; consumption is a load",
            generator,
            "p_mw",
        )
    if generator.voltage_setpoint_pu is not None and generator.voltage_setpoint_pu <= 0:
        out.add(
            ErrorCode.INVALID_GENERATOR_VOLTAGE_SETPOINT,
            "voltage_setpoint_pu must be greater than 0",
            generator,
            "voltage_setpoint_pu",
        )
    if (
        generator.min_q_mvar is not None
        and generator.max_q_mvar is not None
        and generator.min_q_mvar > generator.max_q_mvar
    ):
        out.add(
            ErrorCode.INVALID_GENERATOR_REACTIVE_LIMITS,
            "min_q_mvar must not exceed max_q_mvar",
            generator,
            "min_q_mvar",
        )
    if generator.rated_power_mva is not None:
        if generator.rated_power_mva <= 0:
            out.add(
                ErrorCode.INVALID_GENERATOR_RATED_POWER,
                "rated_power_mva must be greater than 0",
                generator,
                "rated_power_mva",
            )
        else:
            # What is known before solving: p alone in voltage_control mode, where the
            # reactive power is a result.
            apparent = math.hypot(generator.p_mw, generator.q_mvar or 0.0)
            if apparent > generator.rated_power_mva * (1 + _RELATIVE_SLACK):
                out.add(
                    ErrorCode.GENERATOR_EXCEEDS_RATED_POWER,
                    "The set-point exceeds rated_power_mva",
                    generator,
                    "rated_power_mva",
                )


def _check_switch(
    out: _Collector,
    switch: Switch,
    buses: dict[str, Bus],
    lines: dict[str, Line],
    transformers: dict[str, Transformer],
) -> None:
    if not isinstance(switch.closed, bool):
        out.add(ErrorCode.INVALID_SWITCH_STATE, "closed must be true or false", switch, "closed")
    if switch.kind not in SWITCH_KINDS:
        out.add(
            ErrorCode.INVALID_SWITCH_KIND,
            "kind must be one of: " + ", ".join(SWITCH_KINDS),
            switch,
            "kind",
        )
    if switch.bus_id not in buses:
        out.add(ErrorCode.UNKNOWN_BUS_REFERENCE, "bus_id refers to no bus", switch, "bus_id")

    if switch.element_type not in SWITCH_ELEMENT_TYPES:
        out.add(
            ErrorCode.INVALID_SWITCH_ELEMENT_TYPE,
            'element_type must be "line", "transformer" or "bus"',
            switch,
            "element_type",
        )
        return

    terminals: tuple[str, ...]
    if switch.element_type == "line":
        line = lines.get(switch.element_id) if isinstance(switch.element_id, str) else None
        if line is None:
            out.add(
                ErrorCode.UNKNOWN_SWITCH_TARGET,
                "element_id refers to no line",
                switch,
                "element_id",
            )
            return
        terminals = (line.from_bus_id, line.to_bus_id)
    elif switch.element_type == "transformer":
        transformer = (
            transformers.get(switch.element_id) if isinstance(switch.element_id, str) else None
        )
        if transformer is None:
            out.add(
                ErrorCode.UNKNOWN_SWITCH_TARGET,
                "element_id refers to no transformer",
                switch,
                "element_id",
            )
            return
        terminals = (transformer.hv_bus_id, transformer.lv_bus_id)
    else:
        other = buses.get(switch.element_id) if isinstance(switch.element_id, str) else None
        if other is None:
            out.add(
                ErrorCode.UNKNOWN_SWITCH_TARGET, "element_id refers to no bus", switch, "element_id"
            )
            return
        if switch.element_id == switch.bus_id:
            out.add(
                ErrorCode.SWITCH_CONNECTS_BUS_TO_ITSELF,
                "A bus-to-bus switch must join two different buses",
                switch,
            )
            return
        own = buses.get(switch.bus_id)
        if (
            own is not None
            and _is_real_number(own.nominal_voltage_kv)
            and _is_real_number(other.nominal_voltage_kv)
            and not math.isclose(
                own.nominal_voltage_kv, other.nominal_voltage_kv, rel_tol=1e-9, abs_tol=0.0
            )
        ):
            out.add(
                ErrorCode.SWITCH_VOLTAGE_MISMATCH,
                "A bus-to-bus switch must join buses of the same nominal voltage",
                switch,
            )
        return

    if switch.bus_id in buses and switch.bus_id not in terminals:
        out.add(
            ErrorCode.SWITCH_NOT_AT_ELEMENT_TERMINAL,
            f"bus_id is not a terminal of the {switch.element_type} it switches",
            switch,
            "bus_id",
        )


def _switch_position_key(switch: Switch) -> tuple[str, str, str] | None:
    """Identifies the place a switch occupies. Two bus-to-bus switches between the same
    pair of buses occupy the same place whichever bus each names first."""
    if not all(isinstance(v, str) for v in (switch.bus_id, switch.element_type, switch.element_id)):
        return None
    if switch.element_type == "bus":
        first, second = sorted((switch.bus_id, switch.element_id))
        return ("bus", first, second)
    return (switch.element_type, switch.element_id, switch.bus_id)


def validate_grid(grid: GridModel) -> tuple[ValidationIssue, ...]:
    """Return every issue found, in a deterministic order. Empty means valid."""
    out = _Collector()

    if not _is_real_number(grid.frequency_hz):
        out.add(ErrorCode.INVALID_NUMBER, "frequency_hz must be a finite real number")
    elif float(grid.frequency_hz) not in SUPPORTED_FREQUENCIES_HZ:
        out.add(ErrorCode.INVALID_FREQUENCY, "frequency_hz must be 50 or 60")

    if not grid.buses:
        out.add(ErrorCode.NO_BUSES, "A grid needs at least one bus")

    groups: tuple[tuple[Element, ...], ...] = (
        grid.buses,
        grid.lines,
        grid.transformers,
        grid.loads,
        grid.generators,
        grid.external_grids,
        grid.switches,
    )
    for group in groups:
        _check_identifiers(out, group)
        for element in group:
            _check_in_service_flag(out, element)

    buses = {bus.id: bus for bus in grid.buses if isinstance(bus.id, str)}
    for bus in grid.buses:
        _check_bus(out, bus)
    for line in grid.lines:
        _check_line(out, line, buses)
    for load in grid.loads:
        _check_load(out, load, buses)
    for source in grid.external_grids:
        _check_external_grid(out, source, buses)
    for transformer in grid.transformers:
        _check_transformer(out, transformer, buses)
    for generator in grid.generators:
        _check_generator(out, generator, buses)

    lines = {line.id: line for line in grid.lines if isinstance(line.id, str)}
    transformers = {t.id: t for t in grid.transformers if isinstance(t.id, str)}
    occupied: set[tuple[str, str, str]] = set()
    for switch in grid.switches:
        _check_switch(out, switch, buses, lines, transformers)
        position = _switch_position_key(switch)
        if position is not None:
            if position in occupied:
                out.add(
                    ErrorCode.DUPLICATE_SWITCH,
                    "Another switch is already at this place",
                    switch,
                )
            occupied.add(position)

    active_sources = [
        source
        for source in grid.external_grids
        if source.in_service and source.bus_id in buses and buses[source.bus_id].in_service
    ]
    if not active_sources:
        out.add(
            ErrorCode.MISSING_EXTERNAL_GRID,
            "No in-service external grid is connected to an in-service bus: "
            "the network has no slack source",
        )
    per_bus = Counter(source.bus_id for source in active_sources)
    reported: set[str] = set()
    for source in active_sources:
        if per_bus[source.bus_id] > 1 and source.bus_id not in reported:
            reported.add(source.bus_id)
            out.add(
                ErrorCode.MULTIPLE_EXTERNAL_GRIDS_ON_BUS,
                "More than one in-service external grid is connected to the same bus",
                source,
                "bus_id",
            )

    # One voltage reference per bus: an external grid or a single voltage-controlled
    # generator. Two would fight over the same voltage.
    slack_buses = {source.bus_id for source in active_sources}
    controlled: set[str] = set()
    for generator in grid.generators:
        if not (
            generator.control_mode == VOLTAGE_CONTROL
            and generator.in_service is True
            and generator.bus_id in buses
        ):
            continue
        if generator.bus_id in slack_buses or generator.bus_id in controlled:
            out.add(
                ErrorCode.MULTIPLE_VOLTAGE_CONTROLLERS_ON_BUS,
                "The bus already has an external grid or another voltage-controlled generator",
                generator,
                "bus_id",
            )
        controlled.add(generator.bus_id)

    return tuple(out.issues)


def ensure_valid(grid: GridModel) -> None:
    issues = validate_grid(grid)
    if issues:
        raise GridValidationError(issues)
