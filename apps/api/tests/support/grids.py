"""Sample grids for the API's tests. Synthetic values, chosen to cover every column."""

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

GRID_TABLES = (
    "grids",
    "buses",
    "lines",
    "transformers",
    "loads",
    "generators",
    "external_grids",
    "switches",
)

SAMPLE_COORDINATES = {"hv": (0.0, 4.0), "a": (0.0, 3.0), "b": (0.0, 2.0), "c": (-1.5, 1.0)}


def sample_grid(name: str = "Sample feeder (synthetic)") -> GridModel:
    """hv --t1-- a --ab-- b --bc-- c, a coupled busbar d, every element type and option.

    The transformer has a tap changer; one generator is constant power, the other voltage
    controlled with limits; there is a switch of each kind, one of them open.
    """

    def line(line_id: str, from_bus: str, to_bus: str) -> Line:
        return Line(
            id=line_id,
            name=f"Line {line_id}",
            from_bus_id=from_bus,
            to_bus_id=to_bus,
            length_km=2.0,
            r_ohm_per_km=0.2,
            x_ohm_per_km=0.1,
            c_nf_per_km=250.0,
            max_i_ka=0.3,
        )

    return GridModel(
        name=name,
        frequency_hz=50.0,
        buses=(
            Bus(id="hv", name="HV", nominal_voltage_kv=110.0),
            Bus(id="a", name="A", nominal_voltage_kv=20.0),
            Bus(id="b", name="B", nominal_voltage_kv=20.0),
            Bus(id="c", name="C", nominal_voltage_kv=20.0),
            Bus(id="d", name="D", nominal_voltage_kv=20.0, in_service=False),
        ),
        lines=(line("ab", "a", "b"), line("bc", "b", "c")),
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
                phase_shift_degree=30.0,
                tap=TapChanger(
                    side="hv",
                    neutral_position=0,
                    min_position=-9,
                    max_position=9,
                    step_percent=1.5,
                    position=-2,
                ),
            ),
        ),
        loads=(
            Load(id="load-b", name="Load B", bus_id="b", p_mw=2.0, q_mvar=0.5),
            Load(id="load-c", name="Load C", bus_id="c", p_mw=1.0, q_mvar=-0.1),
        ),
        generators=(
            Generator(
                id="pv",
                name="Photovoltaic unit",
                bus_id="c",
                p_mw=0.3,
                control_mode="constant_power",
                q_mvar=0.0,
                rated_power_mva=0.4,
            ),
            Generator(
                id="chp",
                name="Combined heat and power unit",
                bus_id="b",
                p_mw=1.0,
                control_mode="voltage_control",
                voltage_setpoint_pu=1.01,
                min_q_mvar=-0.5,
                max_q_mvar=0.5,
            ),
        ),
        external_grids=(
            ExternalGrid(id="upstream", name="Upstream", bus_id="hv", voltage_pu=1.02),
        ),
        switches=(
            Switch(
                id="cb-t1",
                name="CB T1",
                bus_id="hv",
                element_type="transformer",
                element_id="t1",
                kind="circuit_breaker",
            ),
            Switch(
                id="s-bc",
                name="S bc",
                bus_id="c",
                element_type="line",
                element_id="bc",
                closed=False,
            ),
            Switch(
                id="coupler",
                name="Coupler",
                bus_id="c",
                element_type="bus",
                element_id="d",
                kind="disconnector",
            ),
        ),
    )


def plain_grid(name: str) -> GridModel:
    """The same network without a tap changer, generators or switches."""
    grid = sample_grid(name)
    return replace(
        grid,
        transformers=(replace(grid.transformers[0], tap=None),),
        generators=(),
        switches=(),
    )
