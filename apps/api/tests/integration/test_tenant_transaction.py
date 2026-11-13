"""The tenant transaction helper: context is set, scoped to the transaction, and gone
afterwards, whatever way the transaction ends.

Every test here connects as the runtime role, through the same helper the API will use.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from gridwise_api.tenancy import TenantSession, tenant_transaction
from tests.integration.conftest import TestDatabase

pytestmark = pytest.mark.integration

CURRENT_TENANT = text("SELECT core.current_organization_id()")
RAW_SETTING = text("SELECT current_setting('app.current_organization_id', true)")
VISIBLE = text("SELECT slug FROM core.organizations ORDER BY slug")
BACKEND = text("SELECT pg_backend_pid()")


async def _single_connection_engine(database: TestDatabase) -> AsyncEngine:
    # One connection only, so consecutive transactions provably reuse it.
    return create_async_engine(database.app_url, pool_size=1, max_overflow=0, hide_parameters=True)


async def test_the_context_is_set_inside_the_transaction(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, tenants["alpha"]) as session:
        assert session.organization_id == tenants["alpha"]
        assert (await session.execute(CURRENT_TENANT)).scalar_one() == tenants["alpha"]
        assert list((await session.execute(VISIBLE)).scalars()) == ["alpha"]


async def test_the_context_ends_with_a_committed_transaction(
    tenants: dict[str, uuid.UUID], database: TestDatabase
) -> None:
    engine = await _single_connection_engine(database)
    try:
        async with tenant_transaction(engine, tenants["alpha"]) as session:
            first = (await session.execute(BACKEND)).scalar_one()

        async with engine.connect() as connection:
            assert (await connection.execute(BACKEND)).scalar_one() == first  # same connection
            assert (await connection.execute(RAW_SETTING)).scalar_one() in (None, "")
            assert (await connection.execute(CURRENT_TENANT)).scalar_one() is None
            assert list((await connection.execute(VISIBLE)).scalars()) == []
    finally:
        await engine.dispose()


async def test_the_context_ends_with_a_rolled_back_transaction(
    tenants: dict[str, uuid.UUID], database: TestDatabase
) -> None:
    engine = await _single_connection_engine(database)

    class AbortError(Exception):
        pass

    backends: list[int] = []

    async def open_then_abort() -> None:
        async with tenant_transaction(engine, tenants["alpha"]) as session:
            backends.append((await session.execute(BACKEND)).scalar_one())
            raise AbortError

    try:
        with pytest.raises(AbortError):
            await open_then_abort()
        (first,) = backends

        async with engine.connect() as connection:
            assert (await connection.execute(BACKEND)).scalar_one() == first
            assert (await connection.execute(CURRENT_TENANT)).scalar_one() is None
            assert list((await connection.execute(VISIBLE)).scalars()) == []
    finally:
        await engine.dispose()


async def test_the_context_ends_after_a_failed_statement(
    tenants: dict[str, uuid.UUID], database: TestDatabase
) -> None:
    engine = await _single_connection_engine(database)
    backends: list[int] = []

    async def open_then_fail() -> None:
        async with tenant_transaction(engine, tenants["alpha"]) as session:
            backends.append((await session.execute(BACKEND)).scalar_one())
            await session.execute(text("SELECT 1 / 0"))

    try:
        with pytest.raises(DBAPIError):
            await open_then_fail()
        (first,) = backends

        async with engine.connect() as connection:
            assert (await connection.execute(BACKEND)).scalar_one() == first
            assert list((await connection.execute(VISIBLE)).scalars()) == []
    finally:
        await engine.dispose()


async def test_the_next_tenant_on_the_same_connection_sees_only_its_own_rows(
    tenants: dict[str, uuid.UUID], database: TestDatabase
) -> None:
    engine = await _single_connection_engine(database)
    try:
        seen: list[tuple[int, list[str]]] = []
        for slug in ("alpha", "bravo", "alpha"):
            async with tenant_transaction(engine, tenants[slug]) as session:
                backend = (await session.execute(BACKEND)).scalar_one()
                seen.append((backend, list((await session.execute(VISIBLE)).scalars())))
        assert len({backend for backend, _ in seen}) == 1
        assert [visible for _, visible in seen] == [["alpha"], ["bravo"], ["alpha"]]
    finally:
        await engine.dispose()


async def test_concurrent_transactions_for_two_tenants_do_not_mix(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    """Both transactions are open at the same time, on two connections of one pool."""
    both_open = asyncio.Barrier(2)

    async def visible_for(slug: str) -> tuple[int, list[str], uuid.UUID]:
        async with tenant_transaction(app_async_engine, tenants[slug]) as session:
            backend = (await session.execute(BACKEND)).scalar_one()
            await both_open.wait()  # neither proceeds until the other holds its context
            rows = list((await session.execute(VISIBLE)).scalars())
            current = (await session.execute(CURRENT_TENANT)).scalar_one()
            return backend, rows, current

    alpha, bravo = await asyncio.gather(visible_for("alpha"), visible_for("bravo"))
    assert alpha[0] != bravo[0]  # really two connections
    assert alpha[1:] == (["alpha"], tenants["alpha"])
    assert bravo[1:] == (["bravo"], tenants["bravo"])


async def test_an_unknown_tenant_sees_nothing(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, uuid.uuid4()) as session:
        assert list((await session.execute(VISIBLE)).scalars()) == []


@pytest.mark.parametrize("bad", ["d0000000-0000-4000-8000-000000000001", None, 1, b"x"])
async def test_only_a_uuid_is_accepted_as_tenant(
    migrated: None, app_async_engine: AsyncEngine, bad: object
) -> None:
    with pytest.raises(TypeError):
        async with tenant_transaction(app_async_engine, bad):  # type: ignore[arg-type]
            pytest.fail("the transaction must not open")


async def test_a_malformed_context_set_behind_the_helper_fails_closed(
    tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine
) -> None:
    """Defence in depth: even if something else wrote the setting, the policy does not open."""
    async with app_async_engine.connect() as connection:
        await connection.execute(
            text("SELECT set_config('app.current_organization_id', :value, true)"),
            {"value": "' OR true --"},
        )
        with pytest.raises(DataError):
            await connection.execute(VISIBLE)


async def test_a_tenant_session_cannot_be_made_by_hand(app_async_engine: AsyncEngine) -> None:
    async with app_async_engine.connect() as connection:
        with pytest.raises(TypeError):
            TenantSession(connection, uuid.uuid4(), object())
