"""pandapower adapter: the ONLY module in GRIDWISE that imports pandapower.

It translates a ``GridModel`` into a pandapower network, runs the AC Newton-Raphson power
flow, and translates the numbers back. No pandapower type crosses this module's boundary.

Importing pandapower takes seconds and well over 100 MB, so nothing imports this module
implicitly. Import it where power flows are run.
"""

from typing import Any

import pandapower as pp
from pandapower.auxiliary import LoadflowNotConverged

from gridwise_grid_engine.model import GridModel
from gridwise_grid_engine.solver import (
    PowerFlowOptions,
    RawBus,
    RawExternalGrid,
    RawLine,
    RawSolution,
)
from gridwise_grid_engine.topology import in_service_bus_ids, line_is_connected

#: pandapower's internal per-unit power base. It scales the numerics only, not the results.
_BASE_POWER_MVA = 1.0


class PandapowerSolver:
    """AC Newton-Raphson power flow via pandapower.

    Stateless: every ``solve`` builds a new network from the model, so a result can never
    contain values from an earlier call.
    """

    name = "pandapower"
    version: str = pp.__version__

    def solve(self, grid: GridModel, options: PowerFlowOptions) -> RawSolution:
        net, bus_index, line_index, source_index = _build_network(grid)
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
                for bus_id, index in bus_index.items()
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
                for line_id, index in line_index.items()
            },
            external_grids={
                source_id: RawExternalGrid(
                    p_mw=float(net.res_ext_grid.at[index, "p_mw"]),
                    q_mvar=float(net.res_ext_grid.at[index, "q_mvar"]),
                )
                for source_id, index in source_index.items()
            },
        )


def _build_network(
    grid: GridModel,
) -> tuple[Any, dict[str, int], dict[str, int], dict[str, int]]:
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
    return net, bus_index, line_index, source_index
