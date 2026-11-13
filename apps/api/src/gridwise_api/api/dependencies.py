from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from gridwise_api.api.errors import ApiError
from gridwise_api.config import Settings
from gridwise_api.repositories.system import SqlSystemRepository
from gridwise_api.schema_version import EXPECTED_SCHEMA_REVISION
from gridwise_api.services.grids import GridService
from gridwise_api.services.health import HealthService
from gridwise_api.tenancy import DevelopmentTenantUnavailableError, resolve_development_tenant


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_health_service(
    request: Request, settings: Annotated[Settings, Depends(get_app_settings)]
) -> HealthService:
    return HealthService(
        SqlSystemRepository(request.app.state.engine),
        timeout_seconds=settings.readiness_timeout_seconds,
        expected_revision=EXPECTED_SCHEMA_REVISION,
    )


def get_tenant(settings: Annotated[Settings, Depends(get_app_settings)]) -> UUID:
    """The organisation this request acts for.

    Until authentication exists (P6) this is the fixed development tenant, configured on the
    server. It never comes from the request. It is a choice of tenant, not a proof of who
    the caller is: GRIDWISE has no access control yet.
    """
    try:
        return resolve_development_tenant(settings)
    except DevelopmentTenantUnavailableError as error:
        raise ApiError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "development_tenant_not_configured",
            "No development tenant is configured. Set GRIDWISE_DEV_ORGANIZATION_ID "
            "(local and test environments only).",
        ) from error


def get_grid_service(
    request: Request, settings: Annotated[Settings, Depends(get_app_settings)]
) -> GridService:
    return GridService(request.app.state.engine, max_elements=settings.grid_max_elements)
