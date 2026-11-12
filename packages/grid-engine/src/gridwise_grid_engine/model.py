"""The electrical model. Every numeric field carries its unit in its name.

Scope of this model (see docs/domain/grid-engine.md for the full list of limits):

* balanced three-phase system, represented by its positive-sequence single-phase equivalent;
* steady state;
* voltages are line-to-line RMS; powers are three-phase totals.

Objects are immutable value objects. Constructing one does not validate it: call
``validate_grid`` (or ``run_power_flow``, which does) to get every problem at once with a
stable error code.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True, kw_only=True)
class Bus:
    """A network node at one nominal voltage level."""

    id: str
    name: str
    #: Nominal line-to-line voltage in kilovolts. Must be > 0.
    nominal_voltage_kv: float
    in_service: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Line:
    """An overhead line or cable between two buses of the same nominal voltage.

    Modelled as a nominal pi-equivalent: series impedance ``(r + jx) * length`` with half of
    the shunt capacitance at each end. Parameters are per phase (positive sequence).
    """

    id: str
    name: str
    from_bus_id: str
    to_bus_id: str
    #: Route length in kilometres. Must be > 0.
    length_km: float
    #: Series resistance in ohm per kilometre. Must be >= 0.
    r_ohm_per_km: float
    #: Series reactance in ohm per kilometre. Must be >= 0; r and x must not both be 0.
    x_ohm_per_km: float
    #: Shunt capacitance in nanofarad per kilometre. Must be >= 0.
    c_nf_per_km: float
    #: Thermal current limit in kiloampere, used for the loading percentage. Must be > 0.
    max_i_ka: float
    in_service: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class Load:
    """A constant-power (PQ) consumer."""

    id: str
    name: str
    bus_id: str
    #: Three-phase active power drawn, in megawatts. Must be >= 0.
    p_mw: float
    #: Three-phase reactive power drawn, in megavolt-ampere reactive.
    #: Positive is inductive (lagging), negative is capacitive.
    q_mvar: float
    in_service: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalGrid:
    """The connection to the upstream network: the slack (reference) source.

    It holds its bus at a fixed voltage magnitude and angle and supplies whatever active
    and reactive power the network needs.
    """

    id: str
    name: str
    bus_id: str
    #: Voltage magnitude set-point in per unit of the bus's nominal voltage. Must be > 0.
    voltage_pu: float = 1.0
    #: Voltage angle set-point in degrees.
    voltage_angle_degree: float = 0.0
    in_service: bool = True


#: Transformer tap changer sides.
TAP_SIDES = ("hv", "lv")


@dataclass(frozen=True, slots=True, kw_only=True)
class TapChanger:
    """A ratio tap changer: each position changes the voltage ratio by ``step_percent``.

    Phase-shifting tap changers are not modelled.
    """

    #: Winding the taps are on: "hv" or "lv".
    side: str
    #: Position at which the ratio equals the ratio of the rated voltages.
    neutral_position: int
    min_position: int
    max_position: int
    #: Change of the tapped winding's voltage per position, in percent. Must be > 0.
    step_percent: float
    #: Current position. Must lie in [min_position, max_position].
    position: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Transformer:
    """A two-winding transformer between a higher and a lower voltage level.

    Described by its nameplate (rating plate) data. The equivalent circuit derived from it
    is documented in docs/domain/grid-engine.md.
    """

    id: str
    name: str
    hv_bus_id: str
    lv_bus_id: str
    #: Rated apparent power in megavolt-ampere. Must be > 0.
    rated_power_mva: float
    #: Rated voltage of the high-voltage winding in kilovolts. Must be > rated_voltage_lv_kv.
    rated_voltage_hv_kv: float
    #: Rated voltage of the low-voltage winding in kilovolts. Must be > 0.
    rated_voltage_lv_kv: float
    #: Relative short-circuit voltage in percent. Must be > 0.
    short_circuit_voltage_percent: float
    #: Resistive part of the short-circuit voltage in percent. 0 <= value <= the total.
    short_circuit_resistive_percent: float
    #: Iron (no-load) losses in kilowatts. Must be >= 0.
    iron_losses_kw: float
    #: No-load current in percent of the rated current. Must be >= 0 and at least what the
    #: iron losses alone require.
    no_load_current_percent: float
    #: Phase shift of the low-voltage side against the high-voltage side, in degrees.
    phase_shift_degree: float = 0.0
    tap: TapChanger | None = None
    in_service: bool = True


#: Generator control modes.
CONSTANT_POWER = "constant_power"
VOLTAGE_CONTROL = "voltage_control"
GENERATOR_CONTROL_MODES = (CONSTANT_POWER, VOLTAGE_CONTROL)


@dataclass(frozen=True, slots=True, kw_only=True)
class Generator:
    """A generating unit, in one of two control modes.

    ``constant_power``: injects fixed ``p_mw`` and ``q_mvar`` (typical for inverter-coupled
    distributed generation). ``voltage_control``: injects ``p_mw`` and holds its bus at
    ``voltage_setpoint_pu`` by adjusting reactive power, within optional limits.

    A generator never energises a network on its own: only an external grid provides the
    voltage and angle reference.
    """

    id: str
    name: str
    bus_id: str
    #: Three-phase active power injected, in megawatts. Must be >= 0.
    p_mw: float
    control_mode: str
    #: constant_power only: reactive power injected, in megavolt-ampere reactive.
    #: Positive is injection (over-excited), negative is absorption.
    q_mvar: float | None = None
    #: voltage_control only: voltage set-point in per unit of the bus's nominal voltage.
    voltage_setpoint_pu: float | None = None
    #: voltage_control only, optional (both or neither): reactive power limits. When the
    #: set-point would need more, the unit stays at the limit and the voltage is not held.
    min_q_mvar: float | None = None
    max_q_mvar: float | None = None
    #: Optional rated apparent power in megavolt-ampere. Must be > 0 when given.
    rated_power_mva: float | None = None
    in_service: bool = True


#: What a switch connects its bus to.
SWITCH_ELEMENT_TYPES = ("line", "transformer", "bus")
#: Descriptive only: the kind of device has no effect on the calculation.
SWITCH_KINDS = ("circuit_breaker", "load_break_switch", "disconnector", "load_switch")


@dataclass(frozen=True, slots=True, kw_only=True)
class Switch:
    """An ideal (zero-impedance) switch in the model.

    Either between a bus and one end of a line or transformer, or between two buses. An
    open switch at one end of a line or transformer disconnects that end only: the element
    stays energised from its other end if that is connected.

    This is a state of the simulated network. It is not a command and reaches no equipment.
    """

    id: str
    name: str
    bus_id: str
    #: "line", "transformer" or "bus".
    element_type: str
    #: Id of the line, transformer or other bus.
    element_id: str
    closed: bool = True
    kind: str = "load_break_switch"


def _as_tuple[T](items: Iterable[T]) -> tuple[T, ...]:
    return items if isinstance(items, tuple) else tuple(items)


#: The element collections of a ``GridModel``, in a fixed order.
ELEMENT_GROUPS = (
    "buses",
    "lines",
    "transformers",
    "loads",
    "generators",
    "external_grids",
    "switches",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class GridModel:
    """A complete network: the unit of validation, hashing and solving."""

    name: str
    #: System frequency in hertz: 50 or 60.
    frequency_hz: float
    buses: tuple[Bus, ...]
    lines: tuple[Line, ...] = field(default=())
    loads: tuple[Load, ...] = field(default=())
    external_grids: tuple[ExternalGrid, ...] = field(default=())
    transformers: tuple[Transformer, ...] = field(default=())
    generators: tuple[Generator, ...] = field(default=())
    switches: tuple[Switch, ...] = field(default=())

    def __post_init__(self) -> None:
        # Accept any iterable, store tuples: the model must stay hashable and immutable.
        for name in ELEMENT_GROUPS:
            object.__setattr__(self, name, _as_tuple(getattr(self, name)))
