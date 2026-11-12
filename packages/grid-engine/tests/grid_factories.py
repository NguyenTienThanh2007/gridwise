"""Small grids used across the engine tests."""

from dataclasses import replace

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


def two_bus(
    *,
    nominal_voltage_kv: float = 20.0,
    slack_voltage_pu: float = 1.0,
    length_km: float = 5.0,
    r_ohm_per_km: float = 0.2,
    x_ohm_per_km: float = 0.1,
    c_nf_per_km: float = 0.0,
    max_i_ka: float = 0.3,
    p_mw: float = 4.0,
    q_mvar: float = 1.5,
    frequency_hz: float = 50.0,
) -> GridModel:
    """source --line-- load, with the slack on ``source``."""
    return GridModel(
        name="two-bus",
        frequency_hz=frequency_hz,
        buses=(
            Bus(id="source", name="Source", nominal_voltage_kv=nominal_voltage_kv),
            Bus(id="load", name="Load", nominal_voltage_kv=nominal_voltage_kv),
        ),
        lines=(
            Line(
                id="line",
                name="Line",
                from_bus_id="source",
                to_bus_id="load",
                length_km=length_km,
                r_ohm_per_km=r_ohm_per_km,
                x_ohm_per_km=x_ohm_per_km,
                c_nf_per_km=c_nf_per_km,
                max_i_ka=max_i_ka,
            ),
        ),
        loads=(Load(id="demand", name="Demand", bus_id="load", p_mw=p_mw, q_mvar=q_mvar),),
        external_grids=(
            ExternalGrid(id="slack", name="Slack", bus_id="source", voltage_pu=slack_voltage_pu),
        ),
    )


def three_bus_radial() -> GridModel:
    """a --ab-- b --bc-- c, slack on ``a``, a load on ``b`` and on ``c``."""

    def line(line_id: str, from_bus: str, to_bus: str) -> Line:
        return Line(
            id=line_id,
            name=line_id,
            from_bus_id=from_bus,
            to_bus_id=to_bus,
            length_km=2.0,
            r_ohm_per_km=0.2,
            x_ohm_per_km=0.1,
            c_nf_per_km=250.0,
            max_i_ka=0.3,
        )

    return GridModel(
        name="three-bus radial",
        frequency_hz=50.0,
        buses=tuple(Bus(id=b, name=b.upper(), nominal_voltage_kv=20.0) for b in ("a", "b", "c")),
        lines=(line("ab", "a", "b"), line("bc", "b", "c")),
        loads=(
            Load(id="load-b", name="Load B", bus_id="b", p_mw=2.0, q_mvar=0.5),
            Load(id="load-c", name="Load C", bus_id="c", p_mw=1.0, q_mvar=0.3),
        ),
        external_grids=(ExternalGrid(id="slack", name="Slack", bus_id="a", voltage_pu=1.02),),
    )


def with_line(grid: GridModel, line_id: str, **changes: object) -> GridModel:
    return replace(
        grid,
        lines=tuple(
            replace(line, **changes) if line.id == line_id else line  # type: ignore[arg-type]
            for line in grid.lines
        ),
    )


def with_bus(grid: GridModel, bus_id: str, **changes: object) -> GridModel:
    return replace(
        grid,
        buses=tuple(
            replace(bus, **changes) if bus.id == bus_id else bus  # type: ignore[arg-type]
            for bus in grid.buses
        ),
    )


def transformer_feeder(
    *,
    slack_voltage_pu: float = 1.0,
    rated_power_mva: float = 25.0,
    rated_voltage_hv_kv: float = 110.0,
    rated_voltage_lv_kv: float = 20.0,
    short_circuit_voltage_percent: float = 12.0,
    short_circuit_resistive_percent: float = 0.16,
    iron_losses_kw: float = 0.0,
    no_load_current_percent: float = 0.0,
    phase_shift_degree: float = 0.0,
    tap: TapChanger | None = None,
    p_mw: float = 10.0,
    q_mvar: float = 3.0,
) -> GridModel:
    """hv (110 kV, slack) --transformer-- lv (20 kV, one load). No load when p = q = 0."""
    loads = (
        (Load(id="demand", name="Demand", bus_id="lv", p_mw=p_mw, q_mvar=q_mvar),)
        if (p_mw, q_mvar) != (0.0, 0.0)
        else ()
    )
    return GridModel(
        name="transformer feeder",
        frequency_hz=50.0,
        buses=(
            Bus(id="hv", name="HV", nominal_voltage_kv=110.0),
            Bus(id="lv", name="LV", nominal_voltage_kv=20.0),
        ),
        transformers=(
            Transformer(
                id="t1",
                name="T1",
                hv_bus_id="hv",
                lv_bus_id="lv",
                rated_power_mva=rated_power_mva,
                rated_voltage_hv_kv=rated_voltage_hv_kv,
                rated_voltage_lv_kv=rated_voltage_lv_kv,
                short_circuit_voltage_percent=short_circuit_voltage_percent,
                short_circuit_resistive_percent=short_circuit_resistive_percent,
                iron_losses_kw=iron_losses_kw,
                no_load_current_percent=no_load_current_percent,
                phase_shift_degree=phase_shift_degree,
                tap=tap,
            ),
        ),
        loads=loads,
        external_grids=(
            ExternalGrid(id="slack", name="Slack", bus_id="hv", voltage_pu=slack_voltage_pu),
        ),
    )


def substation_feeder() -> GridModel:
    """hv --t1-- a --ab-- b --bc-- c: a transformer feeding the three-bus radial network.

    Loads on ``b`` and ``c``, the slack on ``hv``. The transformer has iron losses and a
    no-load current, the lines have capacitance.
    """
    radial = three_bus_radial()
    return replace(
        radial,
        name="substation feeder",
        buses=(Bus(id="hv", name="HV", nominal_voltage_kv=110.0), *radial.buses),
        transformers=(
            Transformer(
                id="t1",
                name="T1",
                hv_bus_id="hv",
                lv_bus_id="a",
                rated_power_mva=25.0,
                rated_voltage_hv_kv=110.0,
                rated_voltage_lv_kv=20.0,
                short_circuit_voltage_percent=12.0,
                short_circuit_resistive_percent=0.16,
                iron_losses_kw=14.0,
                no_load_current_percent=0.07,
            ),
        ),
        external_grids=(ExternalGrid(id="slack", name="Slack", bus_id="hv", voltage_pu=1.0),),
    )


def constant_power_generator(bus_id: str, p_mw: float, q_mvar: float = 0.0) -> Generator:
    return Generator(
        id="unit",
        name="Unit",
        bus_id=bus_id,
        p_mw=p_mw,
        control_mode="constant_power",
        q_mvar=q_mvar,
    )


def voltage_controlled_generator(
    bus_id: str,
    p_mw: float,
    voltage_setpoint_pu: float,
    *,
    min_q_mvar: float | None = None,
    max_q_mvar: float | None = None,
) -> Generator:
    return Generator(
        id="unit",
        name="Unit",
        bus_id=bus_id,
        p_mw=p_mw,
        control_mode="voltage_control",
        voltage_setpoint_pu=voltage_setpoint_pu,
        min_q_mvar=min_q_mvar,
        max_q_mvar=max_q_mvar,
    )


def switch(
    switch_id: str, bus_id: str, element_type: str, element_id: str, *, closed: bool = True
) -> Switch:
    return Switch(
        id=switch_id,
        name=switch_id,
        bus_id=bus_id,
        element_type=element_type,
        element_id=element_id,
        closed=closed,
    )
