"""Application factory. Run with: uvicorn --factory gridwise_api.main:create_app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from gridwise_api import __version__
from gridwise_api.api.errors import (
    UnhandledExceptionMiddleware,
    http_exception_handler,
    validation_exception_handler,
)
from gridwise_api.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from gridwise_api.api.routes import health, system
from gridwise_api.config import Settings, get_settings
from gridwise_api.db import create_engine
from gridwise_api.logging import configure_logging, get_logger


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger = get_logger(__name__)
    logger.info("api_started", version=__version__, environment=app.state.settings.environment)
    yield
    await app.state.engine.dispose()
    logger.info("api_stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="GRIDWISE API",
        version=__version__,
        description="Simulation, monitoring and decision support. No real-world grid control.",
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.engine = create_engine(settings)  # lazy: no connection is opened here

    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    # Middleware runs outermost-last-added:
    #   RequestContext (request ID, access log) -> CORS -> UnhandledException -> routes
    app.add_middleware(UnhandledExceptionMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET"],
            allow_headers=[REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(system.router)
    return app
