"""Database access for platform health. No business rules live here."""

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

_UNDEFINED_TABLE = "42P01"  # PostgreSQL SQLSTATE


class SystemRepository(Protocol):
    async def ping(self) -> None:
        """Raise if the database cannot answer a trivial query."""

    async def schema_revision(self) -> str | None:
        """Return the applied migration revision, or None if never migrated."""


class SqlSystemRepository:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def ping(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def schema_revision(self) -> str | None:
        async with self._engine.connect() as connection:
            try:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            except ProgrammingError as error:
                # Only "the table does not exist" means "never migrated". Anything else
                # (for example a missing privilege) is a real fault and must surface.
                if getattr(error.orig, "sqlstate", None) == _UNDEFINED_TABLE:
                    return None
                raise
            revision: str | None = result.scalar_one_or_none()
            return revision
