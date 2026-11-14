"""Request and response schemas of the scenario and simulation API (decision 0013).

Requests are strict, as in the grid API: unknown fields are rejected, numbers must be finite
JSON numbers and booleans JSON booleans. Ids are UUID strings.

Responses never contain the organisation id, lease fields, worker ids, the request
fingerprint or the idempotency key: they are tenancy or infrastructure detail, not results.

A scenario changes a copy of the grid that is simulated. ``set_switch`` and
``set_in_service`` change that copy only and reach no equipment
(docs/security/safety-boundary.md).
"""

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gridwise_api.api.schemas.grids import Description, Key, Name
from gridwise_api.simulation.configuration import SimulationConfiguration
from gridwise_api.simulation.states import JobStatus
from gridwise_grid_engine import PowerFlowOptions
from gridwise_grid_engine.scenarios import MAX_MODIFICATIONS, SCENARIO_DOCUMENT_SCHEMA

_DEFAULTS = PowerFlowOptions()

#: A UUID string. Strict models would otherwise refuse the JSON string form.
Id = Annotated[UUID, Field(strict=False)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- scenarios ------------------------------------------------------------------------------

Keys = Annotated[list[Key], Field(min_length=1, max_length=5000)]


class ScaleLoads(_Strict):
    """Multiply ``p_mw`` and ``q_mvar`` of every load, or of the listed loads."""

    type: Literal["scale_loads"]
    factor: float = Field(description="0 < factor <= 100")
    keys: Keys | None = None


class ScaleGeneration(_Strict):
    """Multiply the active power of every generator, or of the listed ones, optionally only
    those of one control mode."""

    type: Literal["scale_generation"]
    factor: float = Field(description="0 <= factor <= 100")
    keys: Keys | None = None
    control_mode: Literal["constant_power", "voltage_control"] | None = None


class SetInService(_Strict):
    """Take an element of the simulated copy in or out of service."""

    type: Literal["set_in_service"]
    element_type: Literal["bus", "line", "transformer", "load", "generator", "external_grid"]
    key: Key
    in_service: bool


class SetSwitch(_Strict):
    """The position of a switch in the simulated copy only. Reaches no equipment."""

    type: Literal["set_switch"]
    key: Key
    closed: bool


Modification = Annotated[
    ScaleLoads | ScaleGeneration | SetInService | SetSwitch, Field(discriminator="type")
]


class ScenarioCreate(_Strict):
    name: Name
    description: Description = ""
    modifications: list[Modification] = Field(max_length=MAX_MODIFICATIONS)

    def document(self) -> dict[str, Any]:
        """The ``gridwise.scenario/1`` document; the engine validates it again."""
        return {
            "schema": SCENARIO_DOCUMENT_SCHEMA,
            "modifications": [item.model_dump(exclude_none=True) for item in self.modifications],
        }


class ScenarioResponse(_Out):
    id: UUID
    name: str
    description: str
    spec_hash: str
    #: The stored ``gridwise.scenario/1`` document, exactly as it will be applied.
    specification: dict[str, Any]
    created_at: datetime


class ScenarioListResponse(_Out):
    items: list[ScenarioResponse]
    total: int
    limit: int
    offset: int


# --- submission -----------------------------------------------------------------------------


class ConfigurationRequest(_Strict):
    """AC Newton-Raphson options; omitted values are the engine's defaults."""

    tolerance_mva: float = Field(default=_DEFAULTS.tolerance_mva, description="0 < value <= 1e-3")
    max_iterations: int = Field(default=_DEFAULTS.max_iterations, description="1 <= value <= 100")

    @model_validator(mode="after")
    def _within_the_engines_bounds(self) -> Self:
        self.configuration()  # ValueError with the engine's own message
        return self

    def configuration(self) -> SimulationConfiguration:
        return SimulationConfiguration(
            tolerance_mva=self.tolerance_mva, max_iterations=self.max_iterations
        )


class SubmissionRequest(_Strict):
    scenario_id: Id | None = Field(
        default=None, description="A stored scenario; none means normal operation"
    )
    configuration: ConfigurationRequest | None = None


# --- jobs -----------------------------------------------------------------------------------


class JobSource(_Out):
    grid_id: UUID | None = Field(description="None once the grid was deleted")
    grid_version: int
    topology_hash: str
    status: Literal["current", "changed", "deleted"] = Field(
        description=(
            "current: the grid is still at this version; changed: it has been edited since; "
            "deleted: it no longer exists. The job solves its own snapshot either way."
        )
    )


class JobScenario(_Out):
    id: UUID | None = Field(description="None for normal operation or a deleted scenario")
    spec_hash: str
    specification: dict[str, Any]


class JobConfiguration(_Out):
    algorithm: str
    tolerance_mva: float
    max_iterations: int
    hash: str


class JobEngine(_Out):
    requested_version: str
    executed_version: str | None
    solver_name: str | None
    solver_version: str | None
    fingerprint: str | None


class JobFailure(_Out):
    code: str
    message: str


class JobLinks(_Out):
    self: str
    result: str
    reproductions: str


class JobResponse(_Out):
    id: UUID
    status: JobStatus
    outcome: Literal["converged", "not_converged"] | None
    attempt: int
    max_attempts: int
    source: JobSource
    scenario: JobScenario
    configuration: JobConfiguration
    engine: JobEngine
    input_snapshot_hash: str
    failure: JobFailure | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancelled_at: datetime | None
    links: JobLinks


class AttemptResponse(_Out):
    attempt: int
    started_at: datetime
    ended_at: datetime | None
    ended_by: str | None


class JobDetailResponse(JobResponse):
    attempts: list[AttemptResponse]


class JobListResponse(_Out):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


# --- results --------------------------------------------------------------------------------


class ExtremeResponse(_Out):
    key: str
    value: float


class TotalsResponse(_Out):
    external_supply_mw: float
    external_supply_mvar: float
    generation_mw: float
    generation_mvar: float
    unavailable_generation_mw: float
    served_load_mw: float
    served_load_mvar: float
    unserved_load_mw: float
    unserved_load_mvar: float
    active_losses_mw: float
    reactive_losses_mvar: float


class SummaryResponse(_Out):
    """``gridwise.result-summary/1``. Every value is None when the run did not converge."""

    schema_: str = Field(alias="schema", serialization_alias="schema")
    converged: bool
    totals: TotalsResponse | None
    min_bus_voltage_pu: ExtremeResponse | None
    max_bus_voltage_pu: ExtremeResponse | None
    max_line_loading_percent: ExtremeResponse | None
    max_transformer_loading_percent: ExtremeResponse | None
    lines_over_rating: int | None
    transformers_over_rating: int | None
    de_energised_buses: int | None
    de_energised_lines: int | None
    de_energised_transformers: int | None
    unsupplied_bus_ids: list[str] | None


class ResultResponse(_Out):
    job_id: UUID
    outcome: Literal["converged", "not_converged"]
    result_hash: str | None = Field(description="None when the run did not converge")
    summary: SummaryResponse
    result: dict[str, Any] | None = Field(
        description=(
            "The stored gridwise.power-flow-result-document/1, unchanged. None when the run "
            "did not converge: a run that did not converge has no values."
        )
    )


# --- reproductions --------------------------------------------------------------------------


class ReproductionResponse(_Out):
    id: UUID
    verdict: Literal[
        "match",
        "mismatch",
        "differs_after_engine_change",
        "result_missing",
        "not_reproducible",
        "snapshot_corrupt",
        "reproduction_failed",
    ]
    reproduced_outcome: Literal["converged", "not_converged"] | None
    reproduced_result_hash: str | None
    engine_version: str | None
    solver_name: str | None
    solver_version: str | None
    created_at: datetime


class ReproductionListResponse(_Out):
    items: list[ReproductionResponse]
    total: int
    limit: int
    offset: int
