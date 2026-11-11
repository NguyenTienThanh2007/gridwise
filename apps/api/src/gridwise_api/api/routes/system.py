from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from gridwise_api import __version__
from gridwise_api.api.dependencies import get_app_settings
from gridwise_api.config import Settings

router = APIRouter(prefix="/api/v1/system", tags=["system"])

OPERATING_NOTICE = (
    "GRIDWISE is a simulation, monitoring and decision-support product. "
    "It does not issue switching commands or control any real grid equipment."
)


class SystemInfo(BaseModel):
    name: Literal["gridwise-api"] = "gridwise-api"
    version: str
    environment: str
    operating_mode: Literal["simulation_and_decision_support"] = "simulation_and_decision_support"
    notice: str = OPERATING_NOTICE


@router.get("/info")
async def info(settings: Annotated[Settings, Depends(get_app_settings)]) -> SystemInfo:
    return SystemInfo(version=__version__, environment=settings.environment)
