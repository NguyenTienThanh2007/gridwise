from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from gridwise_api.api.dependencies import get_health_service
from gridwise_api.services.health import HealthService, ReadinessReport

router = APIRouter(prefix="/health", tags=["health"])


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/live")
async def live() -> Liveness:
    """The process is up. Does not touch any dependency."""
    return Liveness()


@router.get(
    "/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessReport}},
)
async def ready(
    response: Response, service: Annotated[HealthService, Depends(get_health_service)]
) -> ReadinessReport:
    """The API can serve requests: the database is reachable and migrated."""
    report = await service.readiness()
    if not report.is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
