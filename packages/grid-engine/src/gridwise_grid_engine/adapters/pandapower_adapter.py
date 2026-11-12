"""pandapower adapter: the ONLY module in GRIDWISE that imports pandapower.

It translates a ``GridModel`` into a pandapower network, runs the AC Newton-Raphson power
flow, and translates the numbers back. No pandapower type crosses this module's boundary.

Importing pandapower takes seconds and well over 100 MB, so nothing imports this module
implicitly. Import it where power flows are run.
"""

from dataclasses import dataclass
from typing import Any

import pandapower as pp
from pandapower.auxiliary import LoadflowNotConverged

from gridwise_grid_engine.model import VOLTAGE_CONTROL, GridModel
from gridwise_grid_engine.solver import (
    PowerFlowOptions,
    RawBus,
    RawExternalGrid,
    RawGenerator,
    RawLine,
    RawSolution,
    RawTransformer,
)
from gridwise_grid_engine.topology import (
    in_service_bus_ids,
    line_is_connected,
    transformer_is_connected,
)

#: pandapower's internal per-unit power base. It scales the numerics only, not the results.
_BASE_POWER_MVA = 1.0

#: pandapower's codes for what a switch connects its bus to, and for the kind of device.
_SWITCH_ELEMENT_CODE = {"line": "l", "transformer": "t", "bus": "b"}
_SWITCH_KIND_CODE = {
    "circuit_breaker": "CB",
    "load_break_switch": "LBS",
    "disconnector": "DS",
    "load_switch": "LS",
}


@dataclass(frozen=True, slots=True)
class _Network:
    """A pandapower network and where each GRIDWISE element sits in its tables."""

    net: Any
    buses: dict[str, int]
    lines: dict[str, int]
    transformers: dict[str, int]
    external_grids: dict[str, int]
    constant_power_generators: dict[str, int]
    voltage_controlled_generators: dict[str, int]
    enforce_reactive_limits: bool


class PandapowerSolver:
    """AC Newton-Raphson power flow via pandapower.

    Stateless: every ``solve`` builds a new network from the model, so a result can never
    contain values from an earlier call.
    """

    name = "pandapower"
    version: str = pp.__version__

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        network = _build_network(grid)
        net = network.net
        try:
            pp.runpp(
                net,
                algorithm="nr",
                # Flat start: every run begins from 1.0 pu / 0 degrees, never from a
                # previous solution, so the outcome depends on the inputs alone.
                init="flat",
                calculate_voltage_angles=True,
                max_iteration=options.max_iterations,
                tolerance_mva=options.tolerance_mva,
                # Islands are found and switched off by pandapower; the engine checks the
                # outcome against its own energisation analysis.
                check_connectivity=True,
                # Stated, not left to a default: the T equivalent circuit, which is what
                # docs/domain/grid-engine.md describes.
                trafo_model="t",
                # A voltage-controlled generator that reaches a reactive limit stays at
                # the limit and no longer holds its set-point.
                enforce_q_lims=network.enforce_reactive_limits,
                numba=False,
            )
        except LoadflowNotConverged:
            return RawSolution(converged=False)
        if not bool(net.converged):
            return RawSolution(converged=False)

        return RawSolution(
            converged=True,
            buses={
                bus_id: RawBus(
                    voltage_pu=float(net.res_bus.at[index, "vm_pu"]),
                    voltage_angle_degree=float(net.res_bus.at[index, "va_degree"]),
                    p_mw=float(net.res_bus.at[index, "p_mw"]),
                    q_mvar=float(net.res_bus.at[index, "q_mvar"]),
                )
                for bus_id, index in network.buses.items()
            },
            lines={
                line_id: RawLine(
                    p_from_mw=float(net.res_line.at[index, "p_from_mw"]),
                    q_from_mvar=float(net.res_line.at[index, "q_from_mvar"]),
                    p_to_mw=float(net.res_line.at[index, "p_to_mw"]),
                    q_to_mvar=float(net.res_line.at[index, "q_to_mvar"]),
                    current_ka=float(net.res_line.at[index, "i_ka"]),
                    loading_percent=float(net.res_line.at[index, "loading_percent"]),
                )
                for line_id, index in network.lines.items()
            },
            external_grids={
                source_id: RawExternalGrid(
                    p_mw=float(net.res_ext_grid.at[index, "p_mw"]),
                    q_mvar=float(net.res_ext_grid.at[index, "q_mvar"]),
                )
                for source_id, index in network.external_grids.items()
            },
            transformers={
                transformer_id: RawTransformer(
                    p_hv_mw=float(net.res_trafo.at[index, "p_hv_mw"]),
                    q_hv_mvar=float(net.res_trafo.at[index, "q_hv_mvar"]),
                    p_lv_mw=float(net.res_trafo.at[index, "p_lv_mw"]),
                    q_lv_mvar=float(net.res_trafo.at[index, "q_lv_mvar"]),
                    current_hv_ka=float(net.res_trafo.at[index, "i_hv_ka"]),
                    current_lv_ka=float(net.res_trafo.at[index, "i_lv_ka"]),
                    loading_percent=float(net.res_trafo.at[index, "loading_percent"]),
                )
                for transformer_id, index in network.transformers.items()
            },
            generators={
                **{
                    generator_id: RawGenerator(
                        p_mw=float(net.res_sgen.at[index, "p_mw"]),
                        q_mvar=float(net.res_sgen.at[index, "q_mvar"]),
                    )
                    for generator_id, index in network.constant_power_generators.items()
                },
                **{
                    generator_id: RawGenerator(
                        p_mw=float(net.res_gen.at[index, "p_mw"]),
                        q_mvar=float(net.res_gen.at[index, "q_mvar"]),
                    )
                    for generator_id, index in network.voltage_controlled_generators.items()
                },
            },
        )


def _build_network(grid: GridModel) -> _Network:
    net = pp.create_empty_network(
        name=grid.name, f_hz=float(grid.frequency_hz), sn_mva=_BASE_POWER_MVA
    )

    # Effective states are decided by the engine's own rules and passed explicitly, rather
    # than left to how pandapower treats an in-service element on an out-of-service bus.
    live_buses = in_service_bus_ids(grid)

    bus_index: dict[str, int] = {}
    for bus in grid.buses:
        bus_index[bus.id] = int(
            pp.create_bus(
                net, vn_kv=float(bus.nominal_voltage_kv), name=bus.id, in_service=bus.in_service
            )
        )

    line_index: dict[str, int] = {}
    for line in grid.lines:
        line_index[line.id] = int(
            pp.create_line_from_parameters(
                net,
                from_bus=bus_index[line.from_bus_id],
                to_bus=bus_index[line.to_bus_id],
                length_km=float(line.length_km),
                r_ohm_per_km=float(line.r_ohm_per_km),
                x_ohm_per_km=float(line.x_ohm_per_km),
                c_nf_per_km=float(line.c_nf_per_km),
                max_i_ka=float(line.max_i_ka),
                name=line.id,
                in_service=line_is_connected(line, live_buses),
            )
        )

    for load in grid.loads:
        # Constant power: pandapower's default load model (no ZIP components are set).
        pp.create_load(
            net,
            bus=bus_index[load.bus_id],
            p_mw=float(load.p_mw),
            q_mvar=float(load.q_mvar),
            name=load.id,
            in_service=load.in_service and load.bus_id in live_buses,
        )

    source_index: dict[str, int] = {}
    for source in grid.external_grids:
        source_index[source.id] = int(
            pp.create_ext_grid(
                net,
                bus=bus_index[source.bus_id],
                vm_pu=float(source.voltage_pu),
                va_degree=float(source.voltage_angle_degree),
                name=source.id,
                in_service=source.in_service and source.bus_id in live_buses,
            )
        )

    transformer_index: dict[str, int] = {}
    for transformer in grid.transformers:
        tap = transformer.tap
        tap_arguments: dict[str, Any] = (
            {}
            if tap is None
            else {
                "tap_side": tap.side,
                "tap_neutral": int(tap.neutral_position),
                "tap_min": int(tap.min_position),
                "tap_max": int(tap.max_position),
                "tap_step_percent": float(tap.step_percent),
                "tap_pos": int(tap.position),
                "tap_changer_type": "Ratio",
            }
        )
        transformer_index[transformer.id] = int(
            pp.create_transformer_from_parameters(
                net,
                hv_bus=bus_index[transformer.hv_bus_id],
                lv_bus=bus_index[transformer.lv_bus_id],
                sn_mva=float(transformer.rated_power_mva),
                vn_hv_kv=float(transformer.rated_voltage_hv_kv),
                vn_lv_kv=float(transformer.rated_voltage_lv_kv),
                vkr_percent=float(transformer.short_circuit_resistive_percent),
                vk_percent=float(transformer.short_circuit_voltage_percent),
                pfe_kw=float(transformer.iron_losses_kw),
                i0_percent=float(transformer.no_load_current_percent),
                shift_degree=float(transformer.phase_shift_degree),
                name=transformer.id,
                in_service=transformer_is_connected(transformer, live_buses),
                **tap_arguments,
            )
        )

    constant_power_index: dict[str, int] = {}
    voltage_controlled_index: dict[str, int] = {}
    enforce_reactive_limits = False
    for generator in grid.generators:
        active = generator.in_service and generator.bus_id in live_buses
        if generator.control_mode == VOLTAGE_CONTROL:
            limits: dict[str, float] = {}
            if generator.min_q_mvar is not None and generator.max_q_mvar is not None:
                limits = {
                    "min_q_mvar": float(generator.min_q_mvar),
                    "max_q_mvar": float(generator.max_q_mvar),
                }
                enforce_reactive_limits = enforce_reactive_limits or active
            voltage_controlled_index[generator.id] = int(
                pp.create_gen(
                    net,
                    bus=bus_index[generator.bus_id],
                    p_mw=float(generator.p_mw),
                    vm_pu=float(generator.voltage_setpoint_pu),  # type: ignore[arg-type]
                    name=generator.id,
                    in_service=active,
                    **limits,
                )
            )
        else:
            constant_power_index[generator.id] = int(
                pp.create_sgen(
                    net,
                    bus=bus_index[generator.bus_id],
                    p_mw=float(generator.p_mw),
                    q_mvar=float(generator.q_mvar),  # type: ignore[arg-type]
                    name=generator.id,
                    in_service=active,
                )
            )

    element_index = {"line": line_index, "transformer": transformer_index, "bus": bus_index}
    for switch in grid.switches:
        pp.create_switch(
            net,
            bus=bus_index[switch.bus_id],
            element=element_index[switch.element_type][switch.element_id],
            et=_SWITCH_ELEMENT_CODE[switch.element_type],
            closed=switch.closed,
            type=_SWITCH_KIND_CODE[switch.kind],
            name=switch.id,
            z_ohm=0.0,  # ideal: buses joined by a closed bus-to-bus switch are one node
        )

    return _Network(
        net=net,
        buses=bus_index,
        lines=line_index,
        transformers=transformer_index,
        external_grids=source_index,
        constant_power_generators=constant_power_index,
        voltage_controlled_generators=voltage_controlled_index,
        enforce_reactive_limits=enforce_reactive_limits,
    )
