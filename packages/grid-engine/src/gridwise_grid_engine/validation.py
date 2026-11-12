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
from gridwise_grid_engine.model import Bus, ExternalGrid, GridModel, Line, Load

SUPPORTED_FREQUENCIES_HZ = (50.0, 60.0)

_NUMERIC_FIELDS: dict[type, tuple[str, ...]] = {
    Bus: ("nominal_voltage_kv",),
    Line: ("length_km", "r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka"),
    Load: ("p_mw", "q_mvar"),
    ExternalGrid: ("voltage_pu", "voltage_angle_degree"),
}
_ELEMENT_TYPE = {Bus: "bus", Line: "line", Load: "load", ExternalGrid: "external_grid"}

type Element = Bus | Line | Load | ExternalGrid


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
    return valid


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


def validate_grid(grid: GridModel) -> tuple[ValidationIssue, ...]:
    """Return every issue found, in a deterministic order. Empty means valid."""
    out = _Collector()

    if not _is_real_number(grid.frequency_hz):
        out.add(ErrorCode.INVALID_NUMBER, "frequency_hz must be a finite real number")
    elif float(grid.frequency_hz) not in SUPPORTED_FREQUENCIES_HZ:
        out.add(ErrorCode.INVALID_FREQUENCY, "frequency_hz must be 50 or 60")

    if not grid.buses:
        out.add(ErrorCode.NO_BUSES, "A grid needs at least one bus")

    for group in (grid.buses, grid.lines, grid.loads, grid.external_grids):
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

    return tuple(out.issues)


def ensure_valid(grid: GridModel) -> None:
    issues = validate_grid(grid)
    if issues:
        raise GridValidationError(issues)
