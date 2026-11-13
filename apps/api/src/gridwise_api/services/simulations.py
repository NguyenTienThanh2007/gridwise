"""Simulation submission and job rules.

Submitting a simulation runs in one tenant transaction:

1. share-lock the grid row, so its topology cannot change while it is copied;
2. compare its version with the caller's expected version, if one was given;
3. rebuild the grid from its rows and check it against the stored ``topology_hash``;
4. apply the scenario to a copy and validate the result with the engine;
5. store the grid as a base snapshot and the result as the input snapshot (deduplicated);
6. store the job, ``queued``.

Nothing is stored unless all of it succeeds. No power flow runs here, and the solver is
never imported: a separate worker (P1.3b) solves the input snapshot.

There is no authentication. The organisation is whatever the caller passes, which until P6
is the fixed development tenant in local and test environments only.
"""

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids as grid_repository
from gridwise_api.repositories import simulations as repository
from gridwise_api.repositories.grid_mapping import element_keys
from gridwise_api.repositories.simulations import (
    AttemptRecord,
    JobRecord,
    ScenarioRecord,
    SnapshotRecord,
)
from gridwise_api.simulation.configuration import SimulationConfiguration
from gridwise_api.tenancy import TenantSession, tenant_transaction
from gridwise_grid_engine import GridModel, ValidationIssue, __version__, grid_hash, validate_grid
from gridwise_grid_engine.hashing import canonical_json, sha256_hex
from gridwise_grid_engine.scenarios import (
    Scenario,
    ScenarioError,
    ScenarioIssue,
    apply_scenario,
    normal_operation,
    scenario_from_document,
    scenario_hash,
    scenario_text,
)
from gridwise_grid_engine.snapshots import SnapshotError, grid_from_snapshot, snapshot_text

_IDEMPOTENCY_CONSTRAINT = "uq_jobs_organization_idempotency_key"
_SCENARIO_NAME_CONSTRAINT = "uq_scenarios_organization_name"


# --- errors -------------------------------------------------------------------------------


class SimulationServiceError(Exception):
    """Base class of every failure the service reports deliberately."""


class GridNotFoundError(SimulationServiceError):
    """The grid does not exist, or belongs to another tenant."""


class ScenarioNotFoundError(SimulationServiceError):
    """The scenario does not exist, or belongs to another tenant."""


class JobNotFoundError(SimulationServiceError):
    """The job does not exist, or belongs to another tenant."""


class GridVersionConflictError(SimulationServiceError):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"the grid is at version {current_version}")


class ScenarioDocumentInvalidError(SimulationServiceError):
    def __init__(self, issues: tuple[ScenarioIssue, ...]) -> None:
        self.issues = issues
        super().__init__(f"{len(issues)} scenario issue(s)")


class ScenarioNotApplicableError(SimulationServiceError):
    """The scenario names elements this grid does not have."""

    def __init__(self, issues: tuple[ScenarioIssue, ...]) -> None:
        self.issues = issues
        super().__init__(f"{len(issues)} scenario issue(s)")


class SimulatedGridInvalidError(SimulationServiceError):
    """The grid as the scenario changes it is not a valid grid."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__(f"{len(issues)} validation issue(s)")


class SimulatedGridTooLargeError(SimulationServiceError):
    def __init__(self, element_count: int, limit: int) -> None:
        self.element_count = element_count
        self.limit = limit
        super().__init__(f"{element_count} elements, at most {limit} allowed")


class ScenarioNameConflictError(SimulationServiceError):
    """Another scenario of the same organisation has this name."""


class IdempotencyKeyReusedError(SimulationServiceError):
    """The key was used before, for a different request."""


class JobNotCancellableError(SimulationServiceError):
    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"a {status} job cannot be cancelled")


class StoredDataIntegrityError(SimulationServiceError):
    """Stored data does not match its own hash. Never expected; reported, never used."""


# --- results ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Submission:
    job: JobRecord
    #: False when an Idempotency-Key matched an earlier, identical submission.
    created: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class JobDetails:
    job: JobRecord
    attempts: list[AttemptRecord]


# --- helpers ------------------------------------------------------------------------------


def _violated(error: IntegrityError, constraint: str) -> bool:
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None) == constraint


def request_fingerprint(
    *,
    grid_id: UUID,
    scenario_id: UUID | None,
    configuration: SimulationConfiguration,
    expected_grid_version: int | None,
) -> str:
    """What the client asked for. Two requests with one Idempotency-Key must match on this."""
    return sha256_hex(
        canonical_json(
            {
                "schema": "gridwise.simulation-request/1",
                "grid_id": str(grid_id),
                "scenario_id": str(scenario_id) if scenario_id else None,
                "configuration_hash": configuration.hash(),
                "expected_grid_version": expected_grid_version,
            }
        )
    )


def _element_count(model: GridModel) -> int:
    return sum(len(keys) for keys in element_keys(model).values())


# --- the service --------------------------------------------------------------------------


class SimulationService:
    def __init__(self, engine: AsyncEngine, *, max_elements: int) -> None:
        self._engine = engine
        self._max_elements = max_elements

    # --- scenarios ---

    async def create_scenario(
        self, organization_id: UUID, *, name: str, description: str, document: object
    ) -> ScenarioRecord:
        try:
            scenario = scenario_from_document(document)
        except ScenarioError as error:
            raise ScenarioDocumentInvalidError(error.issues) from error
        try:
            async with tenant_transaction(self._engine, organization_id) as session:
                return await repository.insert_scenario(
                    session,
                    name=name,
                    description=description,
                    spec=scenario_text(scenario),
                    spec_hash=scenario_hash(scenario),
                )
        except IntegrityError as error:
            if _violated(error, _SCENARIO_NAME_CONSTRAINT):
                raise ScenarioNameConflictError from error
            raise

    async def get_scenario(self, organization_id: UUID, scenario_id: UUID) -> ScenarioRecord:
        async with tenant_transaction(self._engine, organization_id) as session:
            record = await repository.get_scenario(session, scenario_id)
        if record is None:
            raise ScenarioNotFoundError
        return record

    async def list_scenarios(
        self, organization_id: UUID, *, limit: int, offset: int
    ) -> tuple[list[ScenarioRecord], int]:
        async with tenant_transaction(self._engine, organization_id) as session:
            return await repository.list_scenarios(session, limit=limit, offset=offset)

    async def delete_scenario(self, organization_id: UUID, scenario_id: UUID) -> None:
        """Jobs that used it keep their own copy of its specification."""
        async with tenant_transaction(self._engine, organization_id) as session:
            if not await repository.delete_scenario(session, scenario_id):
                raise ScenarioNotFoundError

    # --- submission ---

    async def submit(
        self,
        organization_id: UUID,
        grid_id: UUID,
        *,
        scenario_id: UUID | None = None,
        configuration: SimulationConfiguration | None = None,
        expected_grid_version: int | None = None,
        idempotency_key: str | None = None,
    ) -> Submission:
        configuration = configuration or SimulationConfiguration()
        fingerprint = request_fingerprint(
            grid_id=grid_id,
            scenario_id=scenario_id,
            configuration=configuration,
            expected_grid_version=expected_grid_version,
        )
        if idempotency_key is not None:
            earlier = await self._job_for_key(organization_id, idempotency_key, fingerprint)
            if earlier is not None:
                return Submission(job=earlier, created=False)
        try:
            job = await self._submit(
                organization_id,
                grid_id,
                scenario_id=scenario_id,
                configuration=configuration,
                expected_grid_version=expected_grid_version,
                idempotency_key=idempotency_key,
                fingerprint=fingerprint,
            )
        except IntegrityError as error:
            # Two submissions with one key at the same time: the other one won.
            if idempotency_key is not None and _violated(error, _IDEMPOTENCY_CONSTRAINT):
                earlier = await self._job_for_key(organization_id, idempotency_key, fingerprint)
                if earlier is not None:
                    return Submission(job=earlier, created=False)
            raise
        return Submission(job=job, created=True)

    async def _job_for_key(
        self, organization_id: UUID, key: str, fingerprint: str
    ) -> JobRecord | None:
        async with tenant_transaction(self._engine, organization_id) as session:
            earlier = await repository.find_job_by_idempotency_key(session, key)
        if earlier is not None and earlier.request_fingerprint != fingerprint:
            raise IdempotencyKeyReusedError
        return earlier

    async def _scenario(
        self, session: TenantSession, scenario_id: UUID | None
    ) -> tuple[Scenario, UUID | None]:
        if scenario_id is None:
            return normal_operation(), None
        record = await repository.get_scenario(session, scenario_id)
        if record is None:
            raise ScenarioNotFoundError
        try:
            return scenario_from_document(json.loads(record.spec)), record.id
        except (ScenarioError, json.JSONDecodeError) as error:  # the database checked it
            raise StoredDataIntegrityError from error

    async def _submit(
        self,
        organization_id: UUID,
        grid_id: UUID,
        *,
        scenario_id: UUID | None,
        configuration: SimulationConfiguration,
        expected_grid_version: int | None,
        idempotency_key: str | None,
        fingerprint: str,
    ) -> JobRecord:
        async with tenant_transaction(self._engine, organization_id) as session:
            grid = await grid_repository.share_lock_grid(session, grid_id)
            if grid is None:
                raise GridNotFoundError
            if expected_grid_version is not None and grid.version != expected_grid_version:
                raise GridVersionConflictError(grid.version)
            stored = await grid_repository.load_grid(session, grid_id)
            if stored is None:  # share-locked a moment ago in this transaction
                raise GridNotFoundError
            if grid_hash(stored.model) != grid.topology_hash:
                raise StoredDataIntegrityError

            scenario, scenario_ref = await self._scenario(session, scenario_id)
            try:
                simulated = apply_scenario(stored.model, scenario)
            except ScenarioError as error:
                raise ScenarioNotApplicableError(error.issues) from error
            count = _element_count(simulated)
            if count > self._max_elements:
                raise SimulatedGridTooLargeError(count, self._max_elements)
            issues = validate_grid(simulated)
            if issues:
                raise SimulatedGridInvalidError(issues)

            base_text = snapshot_text(stored.model)
            input_text = snapshot_text(simulated)
            base_id = await repository.store_snapshot(
                session,
                document=base_text,
                content_hash=grid.topology_hash,
                element_count=_element_count(stored.model),
            )
            input_id = await repository.store_snapshot(
                session,
                document=input_text,
                content_hash=grid_hash(simulated),
                element_count=count,
            )
            return await repository.insert_job(
                session,
                {
                    "source_grid_id": grid_id,
                    "source_grid_version": grid.version,
                    "source_topology_hash": grid.topology_hash,
                    "base_snapshot_id": base_id,
                    "input_snapshot_id": input_id,
                    "scenario_id": scenario_ref,
                    "scenario_spec": scenario_text(scenario),
                    "scenario_spec_hash": scenario_hash(scenario),
                    "configuration": configuration.text(),
                    "configuration_hash": configuration.hash(),
                    "requested_engine_version": __version__,
                    "idempotency_key": idempotency_key,
                    "request_fingerprint": fingerprint,
                },
            )

    # --- jobs ---

    async def get_job(self, organization_id: UUID, job_id: UUID) -> JobDetails:
        async with tenant_transaction(self._engine, organization_id) as session:
            job = await repository.get_job(session, job_id)
            if job is None:
                raise JobNotFoundError
            attempts = await repository.list_attempts(session, job_id)
        return JobDetails(job=job, attempts=attempts)

    async def list_jobs(
        self,
        organization_id: UUID,
        *,
        limit: int,
        offset: int,
        grid_id: UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[JobRecord], int]:
        async with tenant_transaction(self._engine, organization_id) as session:
            return await repository.list_jobs(
                session, limit=limit, offset=offset, grid_id=grid_id, status=status
            )

    async def cancel(self, organization_id: UUID, job_id: UUID) -> JobRecord:
        """Cancel a queued job. A job that has started or ended is not cancellable."""
        async with tenant_transaction(self._engine, organization_id) as session:
            cancelled = await repository.cancel_queued_job(session, job_id)
            if cancelled is not None:
                return cancelled
            current = await repository.get_job(session, job_id)
        if current is None:
            raise JobNotFoundError
        raise JobNotCancellableError(current.status)

    async def input_snapshot(
        self, organization_id: UUID, job_id: UUID
    ) -> tuple[JobRecord, SnapshotRecord]:
        """The exact input of a job, checked against its hash before it is handed out."""
        async with tenant_transaction(self._engine, organization_id) as session:
            job = await repository.get_job(session, job_id)
            if job is None:
                raise JobNotFoundError
            snapshot = await repository.get_snapshot(session, job.input_snapshot_id)
        if snapshot is None:
            raise StoredDataIntegrityError
        try:
            grid_from_snapshot(snapshot.document, expected_hash=snapshot.content_hash)
        except SnapshotError as error:
            raise StoredDataIntegrityError from error
        return job, snapshot
