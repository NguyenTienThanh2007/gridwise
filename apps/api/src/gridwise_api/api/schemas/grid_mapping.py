"""Translation between the HTTP schemas and the engine's model. Pure functions."""

from collections.abc import Mapping
from typing import Any

from gridwise_api.api.schemas.grids import (
    AssetSchema,
    BusSchema,
    DiagramPosition,
    ExternalGridSchema,
    GeneratorSchema,
    LineSchema,
    LoadSchema,
    SwitchSchema,
    TapChangerSchema,
    TopologySchema,
    TransformerSchema,
)
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

type Coordinates = dict[str, tuple[float, float]]


def model_from_topology(name: str, topology: TopologySchema) -> tuple[GridModel, Coordinates]:
    """The engine model a request describes, and the buses' diagram positions."""
    coordinates = {bus.key: (bus.diagram.x, bus.diagram.y) for bus in topology.buses if bus.diagram}
    model = GridModel(
        name=name,
        frequency_hz=topology.frequency_hz,
        buses=tuple(
            Bus(
                id=bus.key,
                name=bus.name,
                nominal_voltage_kv=bus.nominal_voltage_kv,
                in_service=bus.in_service,
            )
            for bus in topology.buses
        ),
        lines=tuple(
            Line(
                id=line.key,
                name=line.name,
                from_bus_id=line.from_bus_key,
                to_bus_id=line.to_bus_key,
                length_km=line.length_km,
                r_ohm_per_km=line.r_ohm_per_km,
                x_ohm_per_km=line.x_ohm_per_km,
                c_nf_per_km=line.c_nf_per_km,
                max_i_ka=line.max_i_ka,
                in_service=line.in_service,
            )
            for line in topology.lines
        ),
        transformers=tuple(
            Transformer(
                id=item.key,
                name=item.name,
                hv_bus_id=item.hv_bus_key,
                lv_bus_id=item.lv_bus_key,
                rated_power_mva=item.rated_power_mva,
                rated_voltage_hv_kv=item.rated_voltage_hv_kv,
                rated_voltage_lv_kv=item.rated_voltage_lv_kv,
                short_circuit_voltage_percent=item.short_circuit_voltage_percent,
                short_circuit_resistive_percent=item.short_circuit_resistive_percent,
                iron_losses_kw=item.iron_losses_kw,
                no_load_current_percent=item.no_load_current_percent,
                phase_shift_degree=item.phase_shift_degree,
                tap=TapChanger(**item.tap.model_dump()) if item.tap else None,
                in_service=item.in_service,
            )
            for item in topology.transformers
        ),
        loads=tuple(
            Load(
                id=load.key,
                name=load.name,
                bus_id=load.bus_key,
                p_mw=load.p_mw,
                q_mvar=load.q_mvar,
                in_service=load.in_service,
            )
            for load in topology.loads
        ),
        generators=tuple(
            Generator(
                id=unit.key,
                name=unit.name,
                bus_id=unit.bus_key,
                p_mw=unit.p_mw,
                control_mode=unit.control_mode,
                q_mvar=unit.q_mvar,
                voltage_setpoint_pu=unit.voltage_setpoint_pu,
                min_q_mvar=unit.min_q_mvar,
                max_q_mvar=unit.max_q_mvar,
                rated_power_mva=unit.rated_power_mva,
                in_service=unit.in_service,
            )
            for unit in topology.generators
        ),
        external_grids=tuple(
            ExternalGrid(
                id=source.key,
                name=source.name,
                bus_id=source.bus_key,
                voltage_pu=source.voltage_pu,
                voltage_angle_degree=source.voltage_angle_degree,
                in_service=source.in_service,
            )
            for source in topology.external_grids
        ),
        switches=tuple(
            Switch(
                id=item.key,
                name=item.name,
                bus_id=item.bus_key,
                element_type=item.element_type,
                element_id=item.element_key,
                closed=item.closed,
                kind=item.kind,
            )
            for item in topology.switches
        ),
    )
    return model, coordinates


def _bus(bus: Bus, coordinates: Mapping[str, tuple[float, float]]) -> BusSchema:
    position = coordinates.get(bus.id)
    return BusSchema(
        key=bus.id,
        name=bus.name,
        nominal_voltage_kv=bus.nominal_voltage_kv,
        in_service=bus.in_service,
        diagram=DiagramPosition(x=position[0], y=position[1]) if position else None,
    )


def asset_schema(element: Any, coordinates: Mapping[str, tuple[float, float]]) -> AssetSchema:
    """The HTTP representation of one engine element."""
    if isinstance(element, Bus):
        return _bus(element, coordinates)
    if isinstance(element, Line):
        return LineSchema(
            key=element.id,
            name=element.name,
            from_bus_key=element.from_bus_id,
            to_bus_key=element.to_bus_id,
            length_km=element.length_km,
            r_ohm_per_km=element.r_ohm_per_km,
            x_ohm_per_km=element.x_ohm_per_km,
            c_nf_per_km=element.c_nf_per_km,
            max_i_ka=element.max_i_ka,
            in_service=element.in_service,
        )
    if isinstance(element, Transformer):
        tap = element.tap
        return TransformerSchema(
            key=element.id,
            name=element.name,
            hv_bus_key=element.hv_bus_id,
            lv_bus_key=element.lv_bus_id,
            rated_power_mva=element.rated_power_mva,
            rated_voltage_hv_kv=element.rated_voltage_hv_kv,
            rated_voltage_lv_kv=element.rated_voltage_lv_kv,
            short_circuit_voltage_percent=element.short_circuit_voltage_percent,
            short_circuit_resistive_percent=element.short_circuit_resistive_percent,
            iron_losses_kw=element.iron_losses_kw,
            no_load_current_percent=element.no_load_current_percent,
            phase_shift_degree=element.phase_shift_degree,
            tap=TapChangerSchema(
                side=tap.side,  # type: ignore[arg-type]
                neutral_position=tap.neutral_position,
                min_position=tap.min_position,
                max_position=tap.max_position,
                step_percent=tap.step_percent,
                position=tap.position,
            )
            if tap
            else None,
            in_service=element.in_service,
        )
    if isinstance(element, Load):
        return LoadSchema(
            key=element.id,
            name=element.name,
            bus_key=element.bus_id,
            p_mw=element.p_mw,
            q_mvar=element.q_mvar,
            in_service=element.in_service,
        )
    if isinstance(element, Generator):
        return GeneratorSchema(
            key=element.id,
            name=element.name,
            bus_key=element.bus_id,
            p_mw=element.p_mw,
            control_mode=element.control_mode,  # type: ignore[arg-type]
            q_mvar=element.q_mvar,
            voltage_setpoint_pu=element.voltage_setpoint_pu,
            min_q_mvar=element.min_q_mvar,
            max_q_mvar=element.max_q_mvar,
            rated_power_mva=element.rated_power_mva,
            in_service=element.in_service,
        )
    if isinstance(element, ExternalGrid):
        return ExternalGridSchema(
            key=element.id,
            name=element.name,
            bus_key=element.bus_id,
            voltage_pu=element.voltage_pu,
            voltage_angle_degree=element.voltage_angle_degree,
            in_service=element.in_service,
        )
    if isinstance(element, Switch):
        return SwitchSchema(
            key=element.id,
            name=element.name,
            bus_key=element.bus_id,
            element_type=element.element_type,  # type: ignore[arg-type]
            element_key=element.element_id,
            closed=element.closed,
            kind=element.kind,  # type: ignore[arg-type]
        )
    raise TypeError(f"not a grid element: {type(element).__name__}")


def topology_from_model(
    model: GridModel, coordinates: Mapping[str, tuple[float, float]]
) -> TopologySchema:
    return TopologySchema(
        frequency_hz=model.frequency_hz,
        buses=[_bus(bus, coordinates) for bus in model.buses],
        lines=[asset_schema(item, coordinates) for item in model.lines],  # type: ignore[misc]
        transformers=[asset_schema(item, coordinates) for item in model.transformers],  # type: ignore[misc]
        loads=[asset_schema(item, coordinates) for item in model.loads],  # type: ignore[misc]
        generators=[asset_schema(item, coordinates) for item in model.generators],  # type: ignore[misc]
        external_grids=[asset_schema(item, coordinates) for item in model.external_grids],  # type: ignore[misc]
        switches=[asset_schema(item, coordinates) for item in model.switches],  # type: ignore[misc]
    )
