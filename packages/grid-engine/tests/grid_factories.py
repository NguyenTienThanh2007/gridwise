"""Small grids used across the engine tests."""

from dataclasses import replace

from gridwise_grid_engine import Bus, ExternalGrid, GridModel, Line, Load


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
