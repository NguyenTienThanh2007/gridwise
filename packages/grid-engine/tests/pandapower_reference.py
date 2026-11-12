"""Test-side helpers that read pandapower's own benchmark networks.

Used to check GRIDWISE's model and its mapping to the solver against networks that
pandapower ships. Only tests may import this: the engine never reads pandapower objects.
"""

import json
import math
import re
from typing import Any

import pandapower as pp

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

_SWITCH_ELEMENT = {"l": "line", "t": "transformer", "b": "bus"}
_SWITCH_KIND = {
    "CB": "circuit_breaker",
    "LBS": "load_break_switch",
    "DS": "disconnector",
    "LS": "load_switch",
}


def _slug(prefix: str, index: int, name: object) -> str:
    """A stable id: the element's own name when it has one, its table index otherwise."""
    if isinstance(name, str) and name.strip():
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{prefix}-{index}"


def _is_set(value: object) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def _require_unmodelled_defaults(net: Any) -> None:
    """Refuse a network that uses something GRIDWISE does not model, rather than drop it."""
    for table in ("shunt", "impedance", "ward", "xward", "storage", "dcline", "trafo3w", "motor"):
        assert len(net[table]) == 0, f"network has {table} elements, which are not modelled"
    assert (net.line.parallel == 1).all()
    assert (net.line.df == 1.0).all()
    assert (net.line.g_us_per_km == 0.0).all()
    assert (net.load.scaling == 1.0).all()
    assert (net.sgen.scaling == 1.0).all()
    assert (net.gen.scaling == 1.0).all()
    assert not net.gen.slack.any()
    for column in (
        "const_z_p_percent",
        "const_i_p_percent",
        "const_z_q_percent",
        "const_i_q_percent",
    ):
        if column in net.load:
            assert (net.load[column] == 0.0).all(), "voltage-dependent loads are not modelled"
    assert (net.trafo.parallel == 1).all()
    assert (net.trafo.df == 1.0).all()
    assert (net.switch.z_ohm == 0.0).all()


def bus_coordinates(net: Any) -> dict[str, tuple[float, float]]:
    """Schematic coordinates stored with the benchmark, keyed by GRIDWISE bus id."""
    coordinates: dict[str, tuple[float, float]] = {}
    for index, row in net.bus.iterrows():
        if _is_set(row.get("geo")):
            x, y = json.loads(row["geo"])["coordinates"]
            coordinates[_slug("bus", index, row["name"])] = (float(x), float(y))
    return coordinates


def grid_model_from_pandapower(net: Any, *, name: str) -> GridModel:
    _require_unmodelled_defaults(net)

    bus_id = {index: _slug("bus", index, row["name"]) for index, row in net.bus.iterrows()}
    line_id = {index: _slug("line", index, row["name"]) for index, row in net.line.iterrows()}
    transformer_id = {
        index: _slug("transformer", index, row["name"]) for index, row in net.trafo.iterrows()
    }

    transformers = []
    for index, row in net.trafo.iterrows():
        tap = None
        if _is_set(row["tap_side"]):
            assert not _is_set(row["tap_step_degree"]) or row["tap_step_degree"] == 0.0
            tap = TapChanger(
                side=str(row["tap_side"]),
                neutral_position=int(row["tap_neutral"]),
                min_position=int(row["tap_min"]),
                max_position=int(row["tap_max"]),
                step_percent=float(row["tap_step_percent"]),
                position=int(row["tap_pos"]),
            )
        transformers.append(
            Transformer(
                id=transformer_id[index],
                name=str(row["name"]),
                hv_bus_id=bus_id[row["hv_bus"]],
                lv_bus_id=bus_id[row["lv_bus"]],
                rated_power_mva=float(row["sn_mva"]),
                rated_voltage_hv_kv=float(row["vn_hv_kv"]),
                rated_voltage_lv_kv=float(row["vn_lv_kv"]),
                short_circuit_voltage_percent=float(row["vk_percent"]),
                short_circuit_resistive_percent=float(row["vkr_percent"]),
                iron_losses_kw=float(row["pfe_kw"]),
                no_load_current_percent=float(row["i0_percent"]),
                phase_shift_degree=float(row["shift_degree"]),
                tap=tap,
                in_service=bool(row["in_service"]),
            )
        )

    generators = [
        Generator(
            id=_slug("generator", index, row["name"]),
            name=str(row["name"]) if _is_set(row["name"]) else f"Generator {index}",
            bus_id=bus_id[row["bus"]],
            p_mw=float(row["p_mw"]),
            control_mode="constant_power",
            q_mvar=float(row["q_mvar"]),
            rated_power_mva=float(row["sn_mva"]) if _is_set(row["sn_mva"]) else None,
            in_service=bool(row["in_service"]),
        )
        for index, row in net.sgen.iterrows()
    ] + [
        Generator(
            id=_slug("unit", index, row["name"]),
            name=str(row["name"]) if _is_set(row["name"]) else f"Unit {index}",
            bus_id=bus_id[row["bus"]],
            p_mw=float(row["p_mw"]),
            control_mode="voltage_control",
            voltage_setpoint_pu=float(row["vm_pu"]),
            min_q_mvar=float(row["min_q_mvar"]) if _is_set(row.get("min_q_mvar")) else None,
            max_q_mvar=float(row["max_q_mvar"]) if _is_set(row.get("max_q_mvar")) else None,
            in_service=bool(row["in_service"]),
        )
        for index, row in net.gen.iterrows()
    ]

    element_id = {"line": line_id, "transformer": transformer_id, "bus": bus_id}
    switches = []
    for index, row in net.switch.iterrows():
        element_type = _SWITCH_ELEMENT[row["et"]]
        switches.append(
            Switch(
                id=f"switch-{index}",
                name=str(row["name"]) if _is_set(row["name"]) else f"Switch {index}",
                bus_id=bus_id[row["bus"]],
                element_type=element_type,
                element_id=element_id[element_type][row["element"]],
                closed=bool(row["closed"]),
                kind=_SWITCH_KIND[row["type"]],
            )
        )

    return GridModel(
        name=name,
        frequency_hz=float(net.f_hz),
        buses=tuple(
            Bus(
                id=bus_id[index],
                name=str(row["name"]) if _is_set(row["name"]) else f"Bus {index}",
                nominal_voltage_kv=float(row["vn_kv"]),
                in_service=bool(row["in_service"]),
            )
            for index, row in net.bus.iterrows()
        ),
        lines=tuple(
            Line(
                id=line_id[index],
                name=str(row["name"]) if _is_set(row["name"]) else f"Line {index}",
                from_bus_id=bus_id[row["from_bus"]],
                to_bus_id=bus_id[row["to_bus"]],
                length_km=float(row["length_km"]),
                r_ohm_per_km=float(row["r_ohm_per_km"]),
                x_ohm_per_km=float(row["x_ohm_per_km"]),
                c_nf_per_km=float(row["c_nf_per_km"]),
                max_i_ka=float(row["max_i_ka"]),
                in_service=bool(row["in_service"]),
            )
            for index, row in net.line.iterrows()
        ),
        transformers=tuple(transformers),
        loads=tuple(
            Load(
                id=_slug("load", index, row["name"]),
                name=str(row["name"]) if _is_set(row["name"]) else f"Load {index}",
                bus_id=bus_id[row["bus"]],
                p_mw=float(row["p_mw"]),
                q_mvar=float(row["q_mvar"]),
                in_service=bool(row["in_service"]),
            )
            for index, row in net.load.iterrows()
        ),
        generators=tuple(generators),
        external_grids=tuple(
            ExternalGrid(
                id=_slug("external-grid", index, row["name"]),
                name=str(row["name"]) if _is_set(row["name"]) else f"External grid {index}",
                bus_id=bus_id[row["bus"]],
                voltage_pu=float(row["vm_pu"]),
                voltage_angle_degree=float(row["va_degree"]),
                in_service=bool(row["in_service"]),
            )
            for index, row in net.ext_grid.iterrows()
        ),
        switches=tuple(switches),
    )


def solve_with_pandapower(net: Any, *, enforce_q_lims: bool = False) -> None:
    """pandapower's own solve of its own network, with the engine's numerical settings."""
    pp.runpp(
        net,
        algorithm="nr",
        init="flat",
        calculate_voltage_angles=True,
        check_connectivity=True,
        trafo_model="t",
        enforce_q_lims=enforce_q_lims,
        tolerance_mva=1e-8,
        max_iteration=10,
        numba=False,
    )
