from typing import Annotated

from fastapi import Depends, Request

from gridwise_api.config import Settings
from gridwise_api.repositories.system import SqlSystemRepository
from gridwise_api.schema_version import EXPECTED_SCHEMA_REVISION
from gridwise_api.services.health import HealthService


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
