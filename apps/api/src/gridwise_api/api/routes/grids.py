"""Grid API: grids, their topology and their assets. HTTP concerns only.

Registered only in the local and test environments (decision 0009). Every request acts for
the fixed development tenant, configured on the server; there is no authentication, and this
is not access control.

Writes need ``If-Match`` with the grid's current version (its ETag). A grid that does not
exist and a grid of another tenant give the same ``404``.

Nothing here runs a power flow. Changing a switch's ``closed`` changes the stored simulation
model only and sends nothing to any equipment.
"""

from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, Path, Query, Response
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from gridwise_api.api.dependencies import get_grid_service, get_tenant
from gridwise_api.api.errors import ApiError, ErrorDetail, ErrorResponse
from gridwise_api.api.preconditions import (
    InvalidIfMatchError,
    PreconditionRequiredError,
    etag,
    expected_version,
)
from gridwise_api.api.schemas.grid_mapping import (
    asset_schema,
    model_from_topology,
    topology_from_model,
)
from gridwise_api.api.schemas.grids import (
    AssetListResponse,
    AssetPatch,
    AssetResponse,
    AssetTypeName,
    ElementCounts,
    GridCreate,
    GridListResponse,
    GridPatch,
    GridResponse,
    SwitchPatch,
    TopologyResponse,
    TopologySchema,
)
from gridwise_api.repositories.grids import StoredGrid
from gridwise_api.services.grids import (
    AssetChange,
    AssetNotFoundError,
    GridInvalidError,
    GridNameConflictError,
    GridNotFoundError,
    GridService,
    GridSummary,
    GridTooLargeError,
    VersionConflictError,
    assets,
    find_asset,
)

router = APIRouter(prefix="/api/v1/grids", tags=["grids"])

Tenant = Annotated[UUID, Depends(get_tenant)]
Service = Annotated[GridService, Depends(get_grid_service)]
GridId = Annotated[UUID, Path(description="The grid's id")]
IfMatch = Annotated[
    str | None,
    Header(description='The grid version you read, as its ETag, for example "3"'),
]

SWITCH_NOTICE = (
    "Changes the position of a switch in the stored simulation model only. "
    "GRIDWISE sends nothing to any real equipment."
)

_ERRORS: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse, "description": "No such grid or asset"},
    422: {"model": ErrorResponse, "description": "Invalid request or invalid grid"},
    503: {"model": ErrorResponse, "description": "No development tenant configured"},
}
_WRITE_ERRORS: dict[int | str, dict[str, object]] = {
    **_ERRORS,
    400: {"model": ErrorResponse, "description": "Malformed If-Match"},
    409: {"model": ErrorResponse, "description": "Grid name already used"},
    412: {"model": ErrorResponse, "description": "The grid changed since you read it"},
    428: {"model": ErrorResponse, "description": "If-Match is required"},
}


# --- error translation ----------------------------------------------------------------


def _not_found() -> ApiError:
    # One message for "absent" and "another tenant's": nothing to tell them apart.
    return ApiError(HTTPStatus.NOT_FOUND, "grid_not_found", "Grid not found")


def _translate(error: Exception) -> ApiError:
    if isinstance(error, GridNotFoundError):
        return _not_found()
    if isinstance(error, AssetNotFoundError):
        return ApiError(HTTPStatus.NOT_FOUND, "asset_not_found", "Asset not found")
    if isinstance(error, VersionConflictError):
        return ApiError(
            HTTPStatus.PRECONDITION_FAILED,
            "version_conflict",
            "The grid has changed since you read it. Read it again and retry.",
            headers={"ETag": etag(error.current_version)},
        )
    if isinstance(error, GridInvalidError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "grid_validation_failed",
            "The grid is not valid. Nothing was stored.",
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
    if isinstance(error, GridNameConflictError):
        return ApiError(
            HTTPStatus.CONFLICT,
            "grid_name_conflict",
            "Another grid of this organisation already has this name",
        )
    if isinstance(error, GridTooLargeError):
        return ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "grid_too_large",
            f"A grid may have at most {error.limit} elements",
        )
    raise error


def _version(if_match: str | None) -> int:
    try:
        return expected_version(if_match)
    except PreconditionRequiredError as error:
        raise ApiError(
            HTTPStatus.PRECONDITION_REQUIRED,
            "precondition_required",
            'Send If-Match with the grid version you read, for example If-Match: "3"',
        ) from error
    except InvalidIfMatchError as error:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_if_match",
            'If-Match must be one strong ETag holding the grid version, for example "3"',
        ) from error


# --- representations --------------------------------------------------------------------


def _grid(summary: GridSummary) -> GridResponse:
    record = summary.record
    return GridResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        frequency_hz=record.frequency_hz,
        # From the stored row, never assumed: anything but "synthetic" fails the response
        # schema rather than being labelled synthetic.
        data_origin=record.data_origin,
        version=record.version,
        topology_hash=record.topology_hash,
        element_counts=ElementCounts(**summary.element_counts),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _topology(stored: StoredGrid) -> TopologyResponse:
    return TopologyResponse(
        grid_id=stored.record.id,
        version=stored.record.version,
        topology_hash=stored.record.topology_hash,
        data_origin=stored.record.data_origin,
        topology=topology_from_model(stored.model, stored.diagram_coordinates),
    )


def _with_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = etag(version)


# --- grids ------------------------------------------------------------------------------


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    responses={**_ERRORS, 409: _WRITE_ERRORS[409]},
    summary="Create a grid with its whole network",
)
async def create_grid(
    body: GridCreate, response: Response, tenant: Tenant, service: Service
) -> GridResponse:
    model, coordinates = model_from_topology(body.name, body.topology)
    try:
        summary = await service.create(
            tenant, model, description=body.description, diagram_coordinates=coordinates
        )
    except (GridInvalidError, GridNameConflictError, GridTooLargeError) as error:
        raise _translate(error) from error
    response.headers["Location"] = f"{router.prefix}/{summary.record.id}"
    _with_etag(response, summary.record.version)
    return _grid(summary)


@router.get("", responses=_ERRORS, summary="List grids")
async def list_grids(
    tenant: Tenant,
    service: Service,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> GridListResponse:
    summaries, total = await service.list(tenant, limit=limit, offset=offset)
    return GridListResponse(
        items=[_grid(summary) for summary in summaries], total=total, limit=limit, offset=offset
    )


@router.get("/{grid_id}", responses=_ERRORS, summary="Read a grid's metadata")
async def get_grid(
    grid_id: GridId, response: Response, tenant: Tenant, service: Service
) -> GridResponse:
    try:
        summary = await service.get(tenant, grid_id)
    except GridNotFoundError as error:
        raise _translate(error) from error
    _with_etag(response, summary.record.version)
    return _grid(summary)


@router.patch("/{grid_id}", responses=_WRITE_ERRORS, summary="Rename or describe a grid")
async def update_grid(
    grid_id: GridId,
    body: GridPatch,
    response: Response,
    tenant: Tenant,
    service: Service,
    if_match: IfMatch = None,
) -> GridResponse:
    version = _version(if_match)
    try:
        summary = await service.update_header(
            tenant,
            grid_id,
            expected_version=version,
            name=body.name,
            description=body.description,
        )
    except (
        GridNotFoundError,
        VersionConflictError,
        GridInvalidError,
        GridNameConflictError,
        GridTooLargeError,
    ) as error:
        raise _translate(error) from error
    _with_etag(response, summary.record.version)
    return _grid(summary)


@router.delete(
    "/{grid_id}",
    status_code=HTTPStatus.NO_CONTENT,
    responses=_WRITE_ERRORS,
    summary="Delete a grid and all of its elements",
)
async def delete_grid(
    grid_id: GridId, tenant: Tenant, service: Service, if_match: IfMatch = None
) -> Response:
    version = _version(if_match)
    try:
        await service.delete(tenant, grid_id, expected_version=version)
    except (GridNotFoundError, VersionConflictError) as error:
        raise _translate(error) from error
    return Response(status_code=HTTPStatus.NO_CONTENT)


# --- topology ---------------------------------------------------------------------------


@router.get("/{grid_id}/topology", responses=_ERRORS, summary="Read the whole network")
async def get_topology(
    grid_id: GridId, response: Response, tenant: Tenant, service: Service
) -> TopologyResponse:
    try:
        stored = await service.get_topology(tenant, grid_id)
    except GridNotFoundError as error:
        raise _translate(error) from error
    _with_etag(response, stored.record.version)
    return _topology(stored)


@router.put(
    "/{grid_id}/topology",
    responses=_WRITE_ERRORS,
    summary="Replace the whole network",
    description="Atomic: either the whole new network is stored, or nothing changes.",
)
async def replace_topology(
    grid_id: GridId,
    body: TopologySchema,
    response: Response,
    tenant: Tenant,
    service: Service,
    if_match: IfMatch = None,
) -> TopologyResponse:
    version = _version(if_match)
    model, coordinates = model_from_topology("", body)  # the service keeps the grid's name
    try:
        stored = await service.replace_topology(
            tenant,
            grid_id,
            expected_version=version,
            model=model,
            diagram_coordinates=coordinates,
        )
    except (
        GridNotFoundError,
        VersionConflictError,
        GridInvalidError,
        GridTooLargeError,
    ) as error:
        raise _translate(error) from error
    _with_etag(response, stored.record.version)
    return _topology(stored)


# --- assets -----------------------------------------------------------------------------

AssetType = Annotated[AssetTypeName, Path(description="Element type")]
AssetKey = Annotated[str, Path(description="The element's key", max_length=200)]


@router.get("/{grid_id}/assets/{asset_type}", responses=_ERRORS, summary="List one element type")
async def list_assets(
    grid_id: GridId,
    asset_type: AssetType,
    response: Response,
    tenant: Tenant,
    service: Service,
) -> AssetListResponse:
    try:
        stored = await service.get_topology(tenant, grid_id)
    except GridNotFoundError as error:
        raise _translate(error) from error
    _with_etag(response, stored.record.version)
    return AssetListResponse(
        grid_id=grid_id,
        grid_version=stored.record.version,
        topology_hash=stored.record.topology_hash,
        type=asset_type,
        items=[
            asset_schema(item, stored.diagram_coordinates) for item in assets(stored, asset_type)
        ],
    )


@router.get("/{grid_id}/assets/{asset_type}/{key}", responses=_ERRORS, summary="Read one element")
async def get_asset(
    grid_id: GridId,
    asset_type: AssetType,
    key: AssetKey,
    response: Response,
    tenant: Tenant,
    service: Service,
) -> AssetResponse:
    try:
        stored = await service.get_topology(tenant, grid_id)
        element = find_asset(stored, asset_type, key)
    except (GridNotFoundError, AssetNotFoundError) as error:
        raise _translate(error) from error
    _with_etag(response, stored.record.version)
    return AssetResponse(
        grid_id=grid_id,
        grid_version=stored.record.version,
        topology_hash=stored.record.topology_hash,
        type=asset_type,
        asset=asset_schema(element, stored.diagram_coordinates),
    )


def _parse_asset_patch(asset_type: AssetTypeName, body: object) -> AssetChange:
    """Switches take ``name`` and ``closed``; every other type ``name`` and ``in_service``."""
    schema = SwitchPatch if asset_type == "switches" else AssetPatch
    try:
        patch = schema.model_validate(body)
    except ValidationError as error:
        raise RequestValidationError(
            [{**item, "loc": ("body", *item["loc"])} for item in error.errors(include_input=False)]
        ) from error
    if isinstance(patch, SwitchPatch):
        return AssetChange(name=patch.name, closed=patch.closed)
    return AssetChange(name=patch.name, in_service=patch.in_service)


@router.patch(
    "/{grid_id}/assets/{asset_type}/{key}",
    responses=_WRITE_ERRORS,
    summary="Change one element's name or state",
    description=(
        "Switches: `name` and/or `closed`. Every other type: `name` and/or `in_service`. "
        "Electrical parameters change only by replacing the topology (decision 0007, D3). "
        + SWITCH_NOTICE
    ),
    # The body is checked against one of two schemas, chosen by the asset type in the path.
    # Documented here, so /docs shows both shapes rather than an arbitrary object.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            AssetPatch.model_json_schema(),
                            SwitchPatch.model_json_schema(),
                        ]
                    }
                }
            },
        }
    },
)
async def update_asset(
    grid_id: GridId,
    asset_type: AssetType,
    key: AssetKey,
    response: Response,
    tenant: Tenant,
    service: Service,
    body: Annotated[
        dict[str, object],
        Body(
            openapi_examples={
                "switch": {"summary": "Close a switch", "value": {"closed": True}},
                "other": {"summary": "Take a line out of service", "value": {"in_service": False}},
            }
        ),
    ],
    if_match: IfMatch = None,
) -> AssetResponse:
    change = _parse_asset_patch(asset_type, body)
    version = _version(if_match)
    try:
        stored = await service.update_asset(
            tenant, grid_id, asset_type, key, expected_version=version, change=change
        )
        element = find_asset(stored, asset_type, key)
    except (
        GridNotFoundError,
        AssetNotFoundError,
        VersionConflictError,
        GridInvalidError,
        GridTooLargeError,
    ) as error:
        raise _translate(error) from error
    _with_etag(response, stored.record.version)
    return AssetResponse(
        grid_id=grid_id,
        grid_version=stored.record.version,
        topology_hash=stored.record.topology_hash,
        type=asset_type,
        asset=asset_schema(element, stored.diagram_coordinates),
    )
