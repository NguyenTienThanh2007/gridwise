"""Tenant context: which organisation a database transaction acts for.

Row-level security in PostgreSQL filters every tenant-owned table by
``core.current_organization_id()``, which reads the transaction-local setting
``app.current_organization_id``. This module is the only place that sets it.

Rules (docs/decisions/0004 and 0008):

* The context is set with ``set_config(..., true)``: it ends with the transaction and
  cannot be seen by the next user of a pooled connection. Never a session-level ``SET``.
* A ``TenantSession`` exists only inside ``tenant_transaction``. Repositories for
  tenant-owned data accept nothing else, so a tenant query cannot run without context.
* The organisation comes from the server: an authenticated identity (P6), or, until then,
  the fixed development tenant, which exists only in local and test environments.

This is the database isolation mechanism. It is not authentication and not access control.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import CursorResult, Executable, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from gridwise_api.config import DEVELOPMENT_ENVIRONMENTS, Settings

_SET_TENANT = text("SELECT set_config('app.current_organization_id', :organization_id, true)")

# Handed to TenantSession by tenant_transaction only.
_OPENED_BY_TENANT_TRANSACTION = object()


class TenantSession:
    """One open transaction whose tenant context is already set."""

    __slots__ = ("_connection", "organization_id")

    def __init__(self, connection: AsyncConnection, organization_id: UUID, token: object) -> None:
        if token is not _OPENED_BY_TENANT_TRANSACTION:
            raise TypeError("A TenantSession can only be obtained from tenant_transaction()")
        self._connection = connection
        self.organization_id = organization_id

    async def execute(
        self,
        statement: Executable,
        parameters: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    ) -> CursorResult[Any]:
        return await self._connection.execute(statement, parameters)


@asynccontextmanager
async def tenant_transaction(
    engine: AsyncEngine, organization_id: UUID
) -> AsyncIterator[TenantSession]:
    """Open a transaction that acts for ``organization_id``.

    Commits when the block ends normally and rolls back when it raises. Either way the
    tenant context ends with the transaction.
    """
    if not isinstance(organization_id, UUID):
        # A string here would most likely have come straight from a request.
        raise TypeError("organization_id must be a UUID")
    async with engine.begin() as connection:
        await connection.execute(_SET_TENANT, {"organization_id": str(organization_id)})
        yield TenantSession(connection, organization_id, _OPENED_BY_TENANT_TRANSACTION)


class DevelopmentTenantUnavailableError(Exception):
    """The fixed development tenant is not available in this deployment."""


def resolve_development_tenant(settings: Settings) -> UUID:
    """The organisation tenant-scoped code runs for while there is no authentication.

    Available only when the environment is local or test AND ``dev_organization_id`` is
    configured. Configuration already refuses the setting elsewhere; the environment is
    checked again here so the rule does not rest on one place.
    """
    if settings.environment not in DEVELOPMENT_ENVIRONMENTS:
        raise DevelopmentTenantUnavailableError(
            "The development tenant exists only in the local and test environments"
        )
    if settings.dev_organization_id is None:
        raise DevelopmentTenantUnavailableError(
            "No development tenant is configured (GRIDWISE_DEV_ORGANIZATION_ID)"
        )
    return settings.dev_organization_id
