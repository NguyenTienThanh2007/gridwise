"""Database engine construction. Connections are opened lazily."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from gridwise_api.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        # Keep bound parameter values out of exception messages and therefore out of logs.
        hide_parameters=True,
    )
