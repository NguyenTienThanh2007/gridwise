"""Simulation API: submit jobs, follow them, read their results. HTTP concerns only.

Registered only in the local and test environments (decision 0013), for the fixed
development tenant; there is no authentication, and this is not access control. A job or
grid of another tenant gives the same ``404`` as one that does not exist.

Submitting stores an immutable input snapshot and a queued job, and returns at once
(``202``). No power flow runs in a request: the worker solves the job in its own process.
Clients poll the job until its status is terminal, then read the result. The API never
triggers a reproduction; that is the worker's ``make reproduce``.

Nothing here reaches any equipment. Results are simulations of stored models, not
measurements.
"""

import json
import re
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Response
from pydantic import AwareDatetime

from gridwise_api.api.dependencies import get_result_service, get_simulation_service, get_tenant
from gridwise_api.api.errors import INTERNAL_ERROR_MESSAGE, ApiError, ErrorDetail, ErrorResponse
from gridwise_api.api.preconditions import (
    InvalidIfMatchError,
    PreconditionRequiredError,
    etag,
    expected_version,
)
from gridwise_api.api.routes.scenarios import scenario_issue_details
from gridwise_api.api.schemas.simulations import (
    AttemptResponse,
    JobConfiguration,
    JobDetailResponse,
    JobEngine,
    JobFailure,
    JobLinks,
    JobListResponse,
    JobResponse,
    JobScenario,
    JobSource,
    ReproductionListResponse,
    ReproductionResponse,
    ResultResponse,
    SubmissionRequest,
    SummaryResponse,
)
from gridwise_api.logging import get_logger
from gridwise_api.repositories.simulations import JobRecord
from gridwise_api.services.results import ResultNotAvailableError, ResultService
from gridwise_api.services.simulations import (
    GridNotFoundError,
    GridVersionConflictError,
    IdempotencyKeyReusedError,
    JobDetails,
    JobNotCancellableError,
    JobNotFoundError,
    JobView,
    ScenarioNotApplicableError,
    ScenarioNotFoundError,
    SimulatedGridInvalidError,
    SimulatedGridTooLargeError,
    SimulationService,
    SourceStatus,
    StoredDataIntegrityError,
)
from gridwise_api.simulation.states import JobStatus
from gridwise_grid_engine.result_summaries import ResultSummary

logger = get_logger("gridwise_api.simulations")

PREFIX = "/api/v1"
router = APIRouter(prefix=PREFIX, tags=["simulations"])

Tenant = Annotated[UUID, Depends(get_tenant)]
Service = Annotated[SimulationService, Depends(get_simulation_service)]
Results = Annotated[ResultService, Depends(get_result_service)]
GridId = Annotated[UUID, Path(description="The grid to simulate")]
JobId = Annotated[UUID, Path(description="The simulation job's id")]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=1_000_000)]

#: The same rule as the database's ``idempotency_key_format``: printable ASCII, no spaces.
_IDEMPOTENCY_KEY = re.compile(r"^[!-~]{1,200}$")
REPLAYED_HEADER = "Idempotent-Replayed"

_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "No such job"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
    503: {"model": ErrorResponse, "description": "No development tenant configured"},
}


# --- errors ---------------------------------------------------------------------------------


def _job_not_found() -> ApiError:
    return ApiError(HTTPStatus.NOT_FOUND, "job_not_found", "Simulation job not found")


def _status_detail(status: str) -> list[ErrorDetail]:
    return [ErrorDetail(location=["status"], message=f"The job is {status}", type=status)]


def _integrity_failure(error: StoredDataIntegrityError, **context: object) -> ApiError:
    # Never expected: stored data no longer matches its own hash. Logged; nothing returned.
    logger.error("stored_data_integrity_failure", error_type=type(error).__name__, **context)
    return ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", INTERNAL_ERROR_MESSAGE)


def _translate_submission(error: Exception, grid_id: UUID) -> ApiError:
    if isinstance(error, GridNotFoundError):
        return ApiError(HTTPStatus.NOT_FOUND, "grid_not_found", "Grid not found")
    if isinstance(error, ScenarioNotFoundError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "scenario_not_found",
            "The scenario does not exist",
            details=[
                ErrorDetail(
                    location=["body", "scenario_id"],
                    message="Scenario not found",
                    type="scenario_not_found",
                )
            ],
        )
    if isinstance(error, GridVersionConflictError):
        return ApiError(
            HTTPStatus.PRECONDITION_FAILED,
            "version_conflict",
            "The grid has changed since you read it. Read it again and retry.",
            headers={"ETag": etag(error.current_version)},
        )
    if isinstance(error, IdempotencyKeyReusedError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "idempotency_key_reused",
            "This Idempotency-Key was used for a different request",
        )
    if isinstance(error, ScenarioNotApplicableError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "scenario_not_applicable",
            "The scenario names elements this grid does not have. Nothing was stored.",
            details=scenario_issue_details(error.issues),
        )
    if isinstance(error, SimulatedGridInvalidError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "simulated_grid_invalid",
            "The grid as the scenario changes it is not valid. Nothing was stored.",
            details=[
                ErrorDetail(
                    location=[
                        part
                        for part in (issue.element_type, issue.element_id, issue.field)
                        if part is not None
                    ],
                    message=issue.message,
                    type=issue.code.value,
                )
                for issue in error.issues
            ],
        )
    if isinstance(error, SimulatedGridTooLargeError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "grid_too_large",
            f"A simulated grid may have at most {error.limit} elements",
        )
    if isinstance(error, StoredDataIntegrityError):
        return _integrity_failure(error, grid_id=str(grid_id))
    raise error


def _expected_version(if_match: str | None) -> int | None:
    """Optional on submission: submitting never changes the grid."""
    if if_match is None:
        return None
    try:
        return expected_version(if_match)
    except (PreconditionRequiredError, InvalidIfMatchError) as error:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_if_match",
            'If-Match must be one strong ETag holding the grid version, for example "3"',
        ) from error


def _idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not _IDEMPOTENCY_KEY.match(value):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_idempotency_key",
            "Idempotency-Key must be 1-200 printable ASCII characters without spaces",
        )
    return value


# --- representations ------------------------------------------------------------------------


def _links(job_id: UUID) -> JobLinks:
    base = f"{PREFIX}/simulations/{job_id}"
    return JobLinks(self=base, result=f"{base}/result", reproductions=f"{base}/reproductions")


def _configuration(job: JobRecord) -> JobConfiguration:
    document = json.loads(job.configuration)
    options = document["options"]
    return JobConfiguration(
        algorithm=document["algorithm"],
        tolerance_mva=options["tolerance_mva"],
        # Canonical JSON writes every number as a decimal: 10 is stored as 10.0.
        max_iterations=int(options["max_iterations"]),
        hash=job.configuration_hash,
    )


def _job_fields(job: JobRecord, source_status: SourceStatus) -> dict[str, object]:
    return {
        "id": job.id,
        "status": JobStatus(job.status),
        "outcome": job.outcome,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "source": JobSource(
            grid_id=job.source_grid_id,
            grid_version=job.source_grid_version,
            topology_hash=job.source_topology_hash,
            status=source_status,
        ),
        "scenario": JobScenario(
            id=job.scenario_id,
            spec_hash=job.scenario_spec_hash,
            specification=json.loads(job.scenario_spec),
        ),
        "configuration": _configuration(job),
        "engine": JobEngine(
            requested_version=job.requested_engine_version,
            executed_version=job.executed_engine_version,
            solver_name=job.solver_name,
            solver_version=job.solver_version,
            fingerprint=job.engine_fingerprint,
        ),
        "failure": (
            JobFailure(code=job.failure_code, message=job.failure_message)
            if job.failure_code is not None and job.failure_message is not None
            else None
        ),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "cancelled_at": job.cancelled_at,
        "links": _links(job.id),
    }


def _job(view: JobView) -> JobResponse:
    # The snapshot's id is internal; its hash identifies the input.
    return JobResponse.model_validate(
        {**_job_fields(view.job, view.source_status), "input_snapshot_hash": view.input_hash}
    )


def _detail(details: JobDetails) -> JobDetailResponse:
    return JobDetailResponse.model_validate(
        {
            **_job_fields(details.job, details.source_status),
            "input_snapshot_hash": details.input_hash,
            "attempts": [
                AttemptResponse(
                    attempt=item.attempt,
                    started_at=item.started_at,
                    ended_at=item.ended_at,
                    ended_by=item.ended_by,
                )
                for item in details.attempts
            ],
        }
    )


def _summary(summary: ResultSummary) -> SummaryResponse:
    def extreme(value: object) -> dict[str, object] | None:
        return None if value is None else {"key": value.key, "value": value.value}  # type: ignore[attr-defined]

    totals = summary.totals
    return SummaryResponse.model_validate(
        {
            "schema": summary.schema,
            "converged": summary.converged,
            "totals": None
            if totals is None
            else {name: getattr(totals, name) for name in totals.__dataclass_fields__},
            "min_bus_voltage_pu": extreme(summary.min_bus_voltage_pu),
            "max_bus_voltage_pu": extreme(summary.max_bus_voltage_pu),
            "max_line_loading_percent": extreme(summary.max_line_loading_percent),
            "max_transformer_loading_percent": extreme(summary.max_transformer_loading_percent),
            "lines_over_rating": summary.lines_over_rating,
            "transformers_over_rating": summary.transformers_over_rating,
            "de_energised_buses": summary.de_energised_buses,
            "de_energised_lines": summary.de_energised_lines,
            "de_energised_transformers": summary.de_energised_transformers,
            "unsupplied_bus_ids": (
                None if summary.unsupplied_bus_ids is None else list(summary.unsupplied_bus_ids)
            ),
        }
    )


async def _read_detail(service: SimulationService, tenant: UUID, job_id: UUID) -> JobDetailResponse:
    try:
        details = await service.get_job(tenant, job_id)
    except JobNotFoundError as error:
        raise _job_not_found() from error
    except StoredDataIntegrityError as error:
        raise _integrity_failure(error, job_id=str(job_id)) from error
    return _detail(details)


# --- submission -----------------------------------------------------------------------------


@router.post(
    "/grids/{grid_id}/simulations",
    status_code=HTTPStatus.ACCEPTED,
    responses={
        200: {
            "model": JobDetailResponse,
            "description": (
                "An earlier submission with the same Idempotency-Key and the same request; "
                f"the response carries `{REPLAYED_HEADER}: true`"
            ),
        },
        400: {"model": ErrorResponse, "description": "Malformed If-Match or Idempotency-Key"},
        404: {"model": ErrorResponse, "description": "No such grid"},
        412: {"model": ErrorResponse, "description": "The grid changed since you read it"},
        422: {
            "model": ErrorResponse,
            "description": (
                "Invalid request, unknown scenario, a scenario that does not fit the grid, "
                "or an Idempotency-Key used for a different request"
            ),
        },
        500: {"model": ErrorResponse, "description": "Stored data failed its integrity check"},
        503: _ERRORS[503],
    },
    summary="Submit a simulation of a grid",
    description=(
        "Captures the grid as an immutable snapshot, applies the scenario to a copy, and "
        "queues a job. Returns at once; a worker solves the job. Poll the job's `self` link "
        "(for example every second) until its status is `completed`, `failed` or "
        "`cancelled`. `If-Match` is optional: send it to be sure the version you read is the "
        "one simulated. The stored grid is never changed, and nothing reaches any equipment."
    ),
)
async def submit_simulation(
    grid_id: GridId,
    response: Response,
    tenant: Tenant,
    service: Service,
    body: Annotated[SubmissionRequest | None, Body()] = None,
    if_match: Annotated[
        str | None, Header(description='Optional: the grid version you read, e.g. "3"')
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(description="Optional: 1-200 printable ASCII characters, no spaces"),
    ] = None,
) -> JobDetailResponse:
    request = body or SubmissionRequest()
    version = _expected_version(if_match)
    key = _idempotency_key(idempotency_key)
    try:
        submission = await service.submit(
            tenant,
            grid_id,
            scenario_id=request.scenario_id,
            configuration=(
                request.configuration.configuration() if request.configuration else None
            ),
            expected_grid_version=version,
            idempotency_key=key,
        )
    except (
        GridNotFoundError,
        ScenarioNotFoundError,
        GridVersionConflictError,
        IdempotencyKeyReusedError,
        ScenarioNotApplicableError,
        SimulatedGridInvalidError,
        SimulatedGridTooLargeError,
        StoredDataIntegrityError,
    ) as error:
        raise _translate_submission(error, grid_id) from error
    detail = await _read_detail(service, tenant, submission.job.id)
    response.headers["Location"] = detail.links.self
    if not submission.created:
        response.status_code = HTTPStatus.OK
        response.headers[REPLAYED_HEADER] = "true"
    return detail


# --- jobs -----------------------------------------------------------------------------------


@router.get("/simulations", responses=_ERRORS, summary="List simulation jobs, newest first")
async def list_simulations(
    tenant: Tenant,
    service: Service,
    limit: Limit = 50,
    offset: Offset = 0,
    grid_id: Annotated[UUID | None, Query(description="Jobs of this grid only")] = None,
    status: Annotated[JobStatus | None, Query(description="Jobs in this status only")] = None,
    submitted_after: Annotated[
        AwareDatetime | None, Query(description="Submitted at or after (with a time zone)")
    ] = None,
    submitted_before: Annotated[
        AwareDatetime | None, Query(description="Submitted before (with a time zone)")
    ] = None,
) -> JobListResponse:
    views, total = await service.list_jobs(
        tenant,
        limit=limit,
        offset=offset,
        grid_id=grid_id,
        status=status.value if status is not None else None,
        submitted_after=submitted_after,
        submitted_before=submitted_before,
    )
    return JobListResponse(
        items=[_job(view) for view in views],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/simulations/{job_id}",
    responses=_ERRORS,
    summary="Read a simulation job",
    description="Status, provenance and attempts. Results are under the `result` link.",
)
async def get_simulation(job_id: JobId, tenant: Tenant, service: Service) -> JobDetailResponse:
    return await _read_detail(service, tenant, job_id)


@router.post(
    "/simulations/{job_id}/cancel",
    responses={
        **_ERRORS,
        409: {"model": ErrorResponse, "description": "The job is no longer queued"},
    },
    summary="Cancel a queued simulation job",
    description="Only a queued job can be cancelled. A running job runs to its end.",
)
async def cancel_simulation(job_id: JobId, tenant: Tenant, service: Service) -> JobDetailResponse:
    try:
        await service.cancel(tenant, job_id)
    except JobNotFoundError as error:
        raise _job_not_found() from error
    except JobNotCancellableError as error:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "job_not_cancellable",
            "Only a queued job can be cancelled",
            details=_status_detail(error.status),
        ) from error
    return await _read_detail(service, tenant, job_id)


@router.get(
    "/simulations/{job_id}/result",
    responses={
        **_ERRORS,
        409: {"model": ErrorResponse, "description": "The job has not completed"},
        500: {"model": ErrorResponse, "description": "Stored data failed its integrity check"},
    },
    summary="Read a completed job's result",
    description=(
        "A converged run returns its summary and the stored result document. A run that "
        "did not converge returns no values at all. Any other job has no result (409). "
        "Results are simulations of the stored model, not measurements."
    ),
)
async def get_simulation_result(job_id: JobId, tenant: Tenant, results: Results) -> ResultResponse:
    try:
        result = await results.get(tenant, job_id)
    except JobNotFoundError as error:
        raise _job_not_found() from error
    except ResultNotAvailableError as error:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "result_not_available",
            "Only a completed job has a result",
            details=_status_detail(error.status),
        ) from error
    except StoredDataIntegrityError as error:
        raise _integrity_failure(error, job_id=str(job_id)) from error
    return ResultResponse(
        job_id=result.job_id,
        outcome="converged" if result.outcome == "converged" else "not_converged",
        result_hash=result.result_hash,
        summary=_summary(result.summary),
        result=json.loads(result.document) if result.document is not None else None,
    )


@router.get(
    "/simulations/{job_id}/reproductions",
    responses=_ERRORS,
    summary="Read a job's reproduction history, newest first",
    description=(
        "Each time the worker re-solved the job's stored input and compared the outcome. "
        "Reading this never reproduces anything: reproduction runs in the worker only."
    ),
)
async def list_simulation_reproductions(
    job_id: JobId, tenant: Tenant, service: Service, limit: Limit = 50, offset: Offset = 0
) -> ReproductionListResponse:
    try:
        records, total = await service.list_reproductions(
            tenant, job_id, limit=limit, offset=offset
        )
    except JobNotFoundError as error:
        raise _job_not_found() from error
    return ReproductionListResponse(
        items=[
            ReproductionResponse.model_validate(
                {
                    "id": record.id,
                    "verdict": record.verdict,
                    "reproduced_outcome": record.reproduced_outcome,
                    "reproduced_result_hash": record.reproduced_result_hash,
                    "engine_version": record.engine_version,
                    "solver_name": record.solver_name,
                    "solver_version": record.solver_version,
                    "created_at": record.created_at,
                }
            )
            for record in records
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
