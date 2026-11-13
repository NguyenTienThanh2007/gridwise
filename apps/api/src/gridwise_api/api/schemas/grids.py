"""Request and response schemas of the grid API.

Strict on purpose: unknown fields are rejected, numbers must be finite JSON numbers (an
integer is accepted where a decimal is expected), booleans must be JSON booleans, and text
must be text. Nothing is coerced, so "false" is never taken for false.

Elements are identified by ``key``, their stable identifier, and refer to each other by
key. Row ids of elements are internal and never appear here. A grid's id is assigned by the
database; a client cannot choose it (decision 0008).

A switch's ``closed`` is a state of the stored simulation model. Changing it sends nothing
to any equipment (docs/security/safety-boundary.md).
"""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


Key = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,200}$"),
    Field(description="Stable identifier: letters, digits, '.', '_' or '-'; 1-200 characters"),
]
Name = Annotated[str, StringConstraints(min_length=1, max_length=200), AfterValidator(_not_blank)]
Description = Annotated[str, StringConstraints(max_length=2000)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


# --- elements (same shape in requests and responses) --------------------------------------


class DiagramPosition(_Strict):
    """Schematic position for drawing. Not geographic, not electrical, not hashed."""

    x: float
    y: float


class BusSchema(_Strict):
    key: Key
    name: Name
    nominal_voltage_kv: float
    in_service: bool = True
    diagram: DiagramPosition | None = None


class LineSchema(_Strict):
    key: Key
    name: Name
    from_bus_key: Key
    to_bus_key: Key
    length_km: float
    r_ohm_per_km: float
    x_ohm_per_km: float
    c_nf_per_km: float
    max_i_ka: float
    in_service: bool = True


class TapChangerSchema(_Strict):
    side: Literal["hv", "lv"]
    neutral_position: int
    min_position: int
    max_position: int
    step_percent: float
    position: int


class TransformerSchema(_Strict):
    key: Key
    name: Name
    hv_bus_key: Key
    lv_bus_key: Key
    rated_power_mva: float
    rated_voltage_hv_kv: float
    rated_voltage_lv_kv: float
    short_circuit_voltage_percent: float
    short_circuit_resistive_percent: float
    iron_losses_kw: float
    no_load_current_percent: float
    phase_shift_degree: float = 0.0
    tap: TapChangerSchema | None = None
    in_service: bool = True


class LoadSchema(_Strict):
    key: Key
    name: Name
    bus_key: Key
    p_mw: float
    q_mvar: float
    in_service: bool = True


class GeneratorSchema(_Strict):
    key: Key
    name: Name
    bus_key: Key
    p_mw: float
    control_mode: Literal["constant_power", "voltage_control"]
    q_mvar: float | None = None
    voltage_setpoint_pu: float | None = None
    min_q_mvar: float | None = None
    max_q_mvar: float | None = None
    rated_power_mva: float | None = None
    in_service: bool = True


class ExternalGridSchema(_Strict):
    key: Key
    name: Name
    bus_key: Key
    voltage_pu: float = 1.0
    voltage_angle_degree: float = 0.0
    in_service: bool = True


class SwitchSchema(_Strict):
    key: Key
    name: Name
    bus_key: Key
    element_type: Literal["line", "transformer", "bus"]
    element_key: Key
    closed: bool = Field(
        default=True,
        description="Position in the simulation model. Not a command to any equipment.",
    )
    kind: Literal["circuit_breaker", "load_break_switch", "disconnector", "load_switch"] = (
        "load_break_switch"
    )


type AssetSchema = (
    BusSchema
    | LineSchema
    | TransformerSchema
    | LoadSchema
    | GeneratorSchema
    | ExternalGridSchema
    | SwitchSchema
)


class TopologySchema(_Strict):
    """A whole network. Every list may be empty except ``buses``, which the engine requires."""

    frequency_hz: float
    buses: list[BusSchema] = Field(default_factory=list)
    lines: list[LineSchema] = Field(default_factory=list)
    transformers: list[TransformerSchema] = Field(default_factory=list)
    loads: list[LoadSchema] = Field(default_factory=list)
    generators: list[GeneratorSchema] = Field(default_factory=list)
    external_grids: list[ExternalGridSchema] = Field(default_factory=list)
    switches: list[SwitchSchema] = Field(default_factory=list)


# --- requests -----------------------------------------------------------------------------


class GridCreate(_Strict):
    name: Name
    description: Description = ""
    topology: TopologySchema


class GridPatch(_Strict):
    name: Name | None = None
    description: Description | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if self.name is None and self.description is None:
            raise ValueError("give name, description or both")
        return self


class AssetPatch(_Strict):
    """Change to any element except a switch: name and/or service state (decision 0007, D3)."""

    name: Name | None = None
    in_service: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if self.name is None and self.in_service is None:
            raise ValueError("give name, in_service or both")
        return self


class SwitchPatch(_Strict):
    """Change to a switch: name and/or position in the simulation model."""

    name: Name | None = None
    closed: bool | None = Field(
        default=None, description="Position in the simulation model. Not a command."
    )

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if self.name is None and self.closed is None:
            raise ValueError("give name, closed or both")
        return self


# --- responses ----------------------------------------------------------------------------


class ElementCounts(BaseModel):
    buses: int
    lines: int
    transformers: int
    loads: int
    generators: int
    external_grids: int
    switches: int


class GridResponse(BaseModel):
    id: UUID
    name: str
    description: str
    frequency_hz: float
    data_origin: Literal["synthetic"] = Field(
        description="Where the data comes from. Only synthetic data exists in GRIDWISE so far."
    )
    version: int = Field(description="Also the ETag. Send it as If-Match to change the grid.")
    topology_hash: str = Field(description="The engine's grid_hash of the stored network")
    element_counts: ElementCounts
    created_at: datetime
    updated_at: datetime


class GridListResponse(BaseModel):
    items: list[GridResponse]
    total: int
    limit: int
    offset: int


class TopologyResponse(BaseModel):
    grid_id: UUID
    version: int
    topology_hash: str
    data_origin: Literal["synthetic"]
    topology: TopologySchema


AssetTypeName = Literal[
    "buses", "lines", "transformers", "loads", "generators", "external_grids", "switches"
]


class AssetResponse(BaseModel):
    grid_id: UUID
    grid_version: int
    topology_hash: str
    type: AssetTypeName
    asset: AssetSchema


class AssetListResponse(BaseModel):
    grid_id: UUID
    grid_version: int
    topology_hash: str
    type: AssetTypeName
    items: list[AssetSchema]
