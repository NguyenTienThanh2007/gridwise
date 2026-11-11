"""Readiness rules.

The API is ready only when the database is reachable **and** its schema is exactly the
revision this build expects. A schema that is behind (migrations not applied yet) or ahead
(a newer release migrated it) is a mismatch: serving requests against it is unsafe.
"""

import asyncio
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from gridwise_api.logging import get_logger
from gridwise_api.repositories.system import SystemRepository

logger = get_logger(__name__)

DatabaseState = Literal["ok", "unavailable", "not_migrated", "schema_mismatch"]


class ReadinessReport(BaseModel):
    status: Literal["ready", "not_ready"]
    database: DatabaseState
    schema_revision: str | None = None
    expected_schema_revision: str

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class HealthService:
    def __init__(
        self, repository: SystemRepository, *, timeout_seconds: float, expected_revision: str
    ) -> None:
        self._repository = repository
        self._timeout_seconds = timeout_seconds
        self._expected_revision = expected_revision

    def _not_ready(self, database: DatabaseState, revision: str | None = None) -> ReadinessReport:
        return ReadinessReport(
            status="not_ready",
            database=database,
            schema_revision=revision,
            expected_schema_revision=self._expected_revision,
        )

    async def readiness(self) -> ReadinessReport:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await self._repository.ping()
                revision = await self._repository.schema_revision()
        except (SQLAlchemyError, OSError, TimeoutError) as error:
            # Log the class only: driver messages can include connection details.
            logger.warning("readiness_database_unavailable", error_type=type(error).__name__)
            return self._not_ready("unavailable")

        if revision is None:
            logger.warning("readiness_schema_not_migrated", expected=self._expected_revision)
            return self._not_ready("not_migrated")
        if revision != self._expected_revision:
            logger.warning(
                "readiness_schema_mismatch", applied=revision, expected=self._expected_revision
            )
            return self._not_ready("schema_mismatch", revision)
        return ReadinessReport(
            status="ready",
            database="ok",
            schema_revision=revision,
            expected_schema_revision=self._expected_revision,
        )
