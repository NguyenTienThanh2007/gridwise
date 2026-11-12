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


def _as_tuple[T](items: Iterable[T]) -> tuple[T, ...]:
    return items if isinstance(items, tuple) else tuple(items)


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

    def __post_init__(self) -> None:
        # Accept any iterable, store tuples: the model must stay hashable and immutable.
        for name in ("buses", "lines", "loads", "external_grids"):
            object.__setattr__(self, name, _as_tuple(getattr(self, name)))
