"""Translation between the engine's ``GridModel`` and rows of the ``grid`` schema.

Pure functions, no database access. Uses the engine's model types only; it never imports
the solver adapter.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from gridwise_grid_engine import (
    Bus,
    ExternalGrid,
    Generator,
    GridModel,
    Line,
    Load,
    Switch,
    TapChanger,
    Transformer,
)

type Row = dict[str, Any]
type Coordinates = Mapping[str, tuple[float, float]]

#: Element tables in the order rows must be inserted (referenced tables first).
ELEMENT_TABLES = (
    "buses",
    "lines",
    "transformers",
    "loads",
    "generators",
    "external_grids",
    "switches",
)


@dataclass(frozen=True, slots=True)
class ElementIds:
    """Row ids for every element of a grid, by table and element key."""

    by_table: Mapping[str, Mapping[str, UUID]]

    def of(self, table: str, key: str) -> UUID:
        return self.by_table[table][key]


def element_keys(model: GridModel) -> dict[str, list[str]]:
    return {
        "buses": [item.id for item in model.buses],
        "lines": [item.id for item in model.lines],
        "transformers": [item.id for item in model.transformers],
        "loads": [item.id for item in model.loads],
        "generators": [item.id for item in model.generators],
        "external_grids": [item.id for item in model.external_grids],
        "switches": [item.id for item in model.switches],
    }


def assign_ids(model: GridModel, new_id: Callable[[str, str], UUID]) -> ElementIds:
    """``new_id(table, key)`` is called once per element, in a fixed order."""
    return ElementIds(
        {
            table: {key: new_id(table, key) for key in keys}
            for table, keys in element_keys(model).items()
        }
    )


def rows_from_model(
    model: GridModel,
    *,
    organization_id: UUID,
    grid_id: UUID,
    ids: ElementIds,
    diagram_coordinates: Coordinates | None = None,
) -> dict[str, list[Row]]:
    coordinates = diagram_coordinates or {}

    def base(table: str, key: str, name: str) -> Row:
        return {
            "id": ids.of(table, key),
            "organization_id": organization_id,
            "grid_id": grid_id,
            "key": key,
            "name": name,
        }

    def bus(key: str) -> UUID:
        return ids.of("buses", key)

    buses = []
    for item in model.buses:
        x, y = coordinates.get(item.id, (None, None))
        buses.append(
            {
                **base("buses", item.id, item.name),
                "nominal_voltage_kv": item.nominal_voltage_kv,
                "in_service": item.in_service,
                "diagram_x": x,
                "diagram_y": y,
            }
        )

    transformers = []
    for transformer in model.transformers:
        tap = transformer.tap
        transformers.append(
            {
                **base("transformers", transformer.id, transformer.name),
                "hv_bus_id": bus(transformer.hv_bus_id),
                "lv_bus_id": bus(transformer.lv_bus_id),
                "rated_power_mva": transformer.rated_power_mva,
                "rated_voltage_hv_kv": transformer.rated_voltage_hv_kv,
                "rated_voltage_lv_kv": transformer.rated_voltage_lv_kv,
                "short_circuit_voltage_percent": transformer.short_circuit_voltage_percent,
                "short_circuit_resistive_percent": transformer.short_circuit_resistive_percent,
                "iron_losses_kw": transformer.iron_losses_kw,
                "no_load_current_percent": transformer.no_load_current_percent,
                "phase_shift_degree": transformer.phase_shift_degree,
                "tap_side": tap.side if tap else None,
                "tap_neutral_position": tap.neutral_position if tap else None,
                "tap_min_position": tap.min_position if tap else None,
                "tap_max_position": tap.max_position if tap else None,
                "tap_step_percent": tap.step_percent if tap else None,
                "tap_position": tap.position if tap else None,
                "in_service": transformer.in_service,
            }
        )

    switches = []
    for switch in model.switches:
        target = ids.of(
            {"line": "lines", "transformer": "transformers", "bus": "buses"}[switch.element_type],
            switch.element_id,
        )
        switches.append(
            {
                **base("switches", switch.id, switch.name),
                "bus_id": bus(switch.bus_id),
                "line_id": target if switch.element_type == "line" else None,
                "transformer_id": target if switch.element_type == "transformer" else None,
                "other_bus_id": target if switch.element_type == "bus" else None,
                "closed": switch.closed,
                "kind": switch.kind,
            }
        )

    return {
        "buses": buses,
        "lines": [
            {
                **base("lines", line.id, line.name),
                "from_bus_id": bus(line.from_bus_id),
                "to_bus_id": bus(line.to_bus_id),
                "length_km": line.length_km,
                "r_ohm_per_km": line.r_ohm_per_km,
                "x_ohm_per_km": line.x_ohm_per_km,
                "c_nf_per_km": line.c_nf_per_km,
                "max_i_ka": line.max_i_ka,
                "in_service": line.in_service,
            }
            for line in model.lines
        ],
        "transformers": transformers,
        "loads": [
            {
                **base("loads", load.id, load.name),
                "bus_id": bus(load.bus_id),
                "p_mw": load.p_mw,
                "q_mvar": load.q_mvar,
                "in_service": load.in_service,
            }
            for load in model.loads
        ],
        "generators": [
            {
                **base("generators", generator.id, generator.name),
                "bus_id": bus(generator.bus_id),
                "p_mw": generator.p_mw,
                "control_mode": generator.control_mode,
                "q_mvar": generator.q_mvar,
                "voltage_setpoint_pu": generator.voltage_setpoint_pu,
                "min_q_mvar": generator.min_q_mvar,
                "max_q_mvar": generator.max_q_mvar,
                "rated_power_mva": generator.rated_power_mva,
                "in_service": generator.in_service,
            }
            for generator in model.generators
        ],
        "external_grids": [
            {
                **base("external_grids", source.id, source.name),
                "bus_id": bus(source.bus_id),
                "voltage_pu": source.voltage_pu,
                "voltage_angle_degree": source.voltage_angle_degree,
                "in_service": source.in_service,
            }
            for source in model.external_grids
        ],
        "switches": switches,
    }


def _switch_target(
    row: Mapping[str, Any], key_of: Mapping[str, Mapping[UUID, str]]
) -> tuple[str, str]:
    for column, table, element_type in (
        ("line_id", "lines", "line"),
        ("transformer_id", "transformers", "transformer"),
        ("other_bus_id", "buses", "bus"),
    ):
        if row[column] is not None:
            return element_type, key_of[table][row[column]]
    raise ValueError("switch row has no target")  # excluded by a database check


def model_from_rows(
    *, name: str, frequency_hz: float, rows: Mapping[str, Iterable[Mapping[str, Any]]]
) -> tuple[GridModel, dict[str, tuple[float, float]]]:
    """Rebuild the engine model and the diagram coordinates. Elements are ordered by key."""
    ordered = {table: sorted(rows[table], key=lambda row: row["key"]) for table in ELEMENT_TABLES}
    key_of = {
        table: {row["id"]: row["key"] for row in ordered[table]}
        for table in ("buses", "lines", "transformers")
    }
    bus_key = key_of["buses"]

    def tap(row: Mapping[str, Any]) -> TapChanger | None:
        if row["tap_side"] is None:
            return None
        return TapChanger(
            side=row["tap_side"],
            neutral_position=row["tap_neutral_position"],
            min_position=row["tap_min_position"],
            max_position=row["tap_max_position"],
            step_percent=row["tap_step_percent"],
            position=row["tap_position"],
        )

    switches = []
    for row in ordered["switches"]:
        element_type, element_id = _switch_target(row, key_of)
        switches.append(
            Switch(
                id=row["key"],
                name=row["name"],
                bus_id=bus_key[row["bus_id"]],
                element_type=element_type,
                element_id=element_id,
                closed=row["closed"],
                kind=row["kind"],
            )
        )

    model = GridModel(
        name=name,
        frequency_hz=frequency_hz,
        buses=tuple(
            Bus(
                id=row["key"],
                name=row["name"],
                nominal_voltage_kv=row["nominal_voltage_kv"],
                in_service=row["in_service"],
            )
            for row in ordered["buses"]
        ),
        lines=tuple(
            Line(
                id=row["key"],
                name=row["name"],
                from_bus_id=bus_key[row["from_bus_id"]],
                to_bus_id=bus_key[row["to_bus_id"]],
                length_km=row["length_km"],
                r_ohm_per_km=row["r_ohm_per_km"],
                x_ohm_per_km=row["x_ohm_per_km"],
                c_nf_per_km=row["c_nf_per_km"],
                max_i_ka=row["max_i_ka"],
                in_service=row["in_service"],
            )
            for row in ordered["lines"]
        ),
        transformers=tuple(
            Transformer(
                id=row["key"],
                name=row["name"],
                hv_bus_id=bus_key[row["hv_bus_id"]],
                lv_bus_id=bus_key[row["lv_bus_id"]],
                rated_power_mva=row["rated_power_mva"],
                rated_voltage_hv_kv=row["rated_voltage_hv_kv"],
                rated_voltage_lv_kv=row["rated_voltage_lv_kv"],
                short_circuit_voltage_percent=row["short_circuit_voltage_percent"],
                short_circuit_resistive_percent=row["short_circuit_resistive_percent"],
                iron_losses_kw=row["iron_losses_kw"],
                no_load_current_percent=row["no_load_current_percent"],
                phase_shift_degree=row["phase_shift_degree"],
                tap=tap(row),
                in_service=row["in_service"],
            )
            for row in ordered["transformers"]
        ),
        loads=tuple(
            Load(
                id=row["key"],
                name=row["name"],
                bus_id=bus_key[row["bus_id"]],
                p_mw=row["p_mw"],
                q_mvar=row["q_mvar"],
                in_service=row["in_service"],
            )
            for row in ordered["loads"]
        ),
        generators=tuple(
            Generator(
                id=row["key"],
                name=row["name"],
                bus_id=bus_key[row["bus_id"]],
                p_mw=row["p_mw"],
                control_mode=row["control_mode"],
                q_mvar=row["q_mvar"],
                voltage_setpoint_pu=row["voltage_setpoint_pu"],
                min_q_mvar=row["min_q_mvar"],
                max_q_mvar=row["max_q_mvar"],
                rated_power_mva=row["rated_power_mva"],
                in_service=row["in_service"],
            )
            for row in ordered["generators"]
        ),
        external_grids=tuple(
            ExternalGrid(
                id=row["key"],
                name=row["name"],
                bus_id=bus_key[row["bus_id"]],
                voltage_pu=row["voltage_pu"],
                voltage_angle_degree=row["voltage_angle_degree"],
                in_service=row["in_service"],
            )
            for row in ordered["external_grids"]
        ),
        switches=tuple(switches),
    )
    coordinates = {
        row["key"]: (row["diagram_x"], row["diagram_y"])
        for row in ordered["buses"]
        if row["diagram_x"] is not None
    }
    return model, coordinates
