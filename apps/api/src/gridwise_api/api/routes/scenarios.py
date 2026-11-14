"""Scenario API: named, immutable scenario documents. HTTP concerns only.

Registered only in the local and test environments (decision 0013), for the fixed
development tenant; there is no authentication, and this is not access control. A scenario
of another tenant gives the same ``404`` as one that does not exist.

A scenario describes changes to a copy of a grid that is simulated. It never changes a
stored grid and reaches no equipment.
"""

import json
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response

from gridwise_api.api.dependencies import get_simulation_service, get_tenant
from gridwise_api.api.errors import ApiError, ErrorDetail, ErrorResponse
from gridwise_api.api.schemas.simulations import (
    ScenarioCreate,
    ScenarioListResponse,
    ScenarioResponse,
)
from gridwise_api.repositories.simulations import ScenarioRecord
from gridwise_api.services.simulations import (
    ScenarioDocumentInvalidError,
    ScenarioNameConflictError,
    ScenarioNotFoundError,
    SimulationService,
)
from gridwise_grid_engine.scenarios import ScenarioIssue

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenarios"])

Tenant = Annotated[UUID, Depends(get_tenant)]
Service = Annotated[SimulationService, Depends(get_simulation_service)]
ScenarioId = Annotated[UUID, Path(description="The scenario's id")]

SCENARIO_NOTICE = (
    "A scenario changes a copy of the grid that is simulated, never the stored grid. "
    "`set_switch` and `set_in_service` change that simulated copy only; GRIDWISE sends "
    "nothing to any real equipment."
)

_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "No such scenario"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
    503: {"model": ErrorResponse, "description": "No development tenant configured"},
}


def scenario_issue_details(issues: tuple[ScenarioIssue, ...]) -> list[ErrorDetail]:
    return [
        ErrorDetail(
            location=(
                ["body", "modifications", issue.modification]
                if issue.modification is not None
                else ["body"]
            ),
            message=issue.message,
            type=issue.code.value,
        )
        for issue in issues
    ]


def _not_found() -> ApiError:
    return ApiError(HTTPStatus.NOT_FOUND, "scenario_not_found", "Scenario not found")


def scenario_response(record: ScenarioRecord) -> ScenarioResponse:
    return ScenarioResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        spec_hash=record.spec_hash,
        specification=json.loads(record.spec),
        created_at=record.created_at,
    )


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    responses={
        **_ERRORS,
        409: {"model": ErrorResponse, "description": "Scenario name already used"},
    },
    summary="Create a scenario",
    description="Scenarios are immutable: to change one, create another. " + SCENARIO_NOTICE,
)
async def create_scenario(
    body: ScenarioCreate, response: Response, tenant: Tenant, service: Service
) -> ScenarioResponse:
    try:
        record = await service.create_scenario(
            tenant, name=body.name, description=body.description, document=body.document()
        )
    except ScenarioDocumentInvalidError as error:
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "scenario_invalid",
            "The scenario is not valid. Nothing was stored.",
            details=scenario_issue_details(error.issues),
        ) from error
    except ScenarioNameConflictError as error:
        raise ApiError(
            HTTPStatus.CONFLICT,
            "scenario_name_conflict",
            "Another scenario of this organisation already has this name",
        ) from error
    response.headers["Location"] = f"{router.prefix}/{record.id}"
    return scenario_response(record)


@router.get("", responses=_ERRORS, summary="List scenarios")
async def list_scenarios(
    tenant: Tenant,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ScenarioListResponse:
    records, total = await service.list_scenarios(tenant, limit=limit, offset=offset)
    return ScenarioListResponse(
        items=[scenario_response(record) for record in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{scenario_id}", responses=_ERRORS, summary="Read a scenario")
async def get_scenario(
    scenario_id: ScenarioId, tenant: Tenant, service: Service
) -> ScenarioResponse:
    try:
        return scenario_response(await service.get_scenario(tenant, scenario_id))
    except ScenarioNotFoundError as error:
        raise _not_found() from error


@router.delete(
    "/{scenario_id}",
    status_code=HTTPStatus.NO_CONTENT,
    responses=_ERRORS,
    summary="Delete a scenario",
    description="Jobs that used it keep their own copy of its specification.",
)
async def delete_scenario(scenario_id: ScenarioId, tenant: Tenant, service: Service) -> Response:
    try:
        await service.delete_scenario(tenant, scenario_id)
    except ScenarioNotFoundError as error:
        raise _not_found() from error
    return Response(status_code=HTTPStatus.NO_CONTENT)
