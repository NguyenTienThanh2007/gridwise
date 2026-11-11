"""Preliminary row-level security tests.

These prove the *database mechanism*: the runtime role is subject to row-level security,
the policy isolates tenants, it fails closed, and tenant context does not leak across a
pooled connection when set transaction-locally.

They do NOT prove that GRIDWISE is tenant-isolated. No API code sets tenant context yet,
there is no authenticated identity to derive it from, and only one table carries a policy.
See docs/decisions/0004 and 0006.
"""

import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DataError

from tests.integration.conftest import TestDatabase

pytestmark = pytest.mark.integration

SET_TENANT = text("SELECT set_config('app.current_organization_id', :organization_id, true)")
VISIBLE_SLUGS = text("SELECT slug FROM core.organizations ORDER BY slug")


@pytest.fixture
def tenants(alembic_config: Config, owner_engine: Engine) -> dict[str, uuid.UUID]:
    command.upgrade(alembic_config, "head")
    insert = text("INSERT INTO core.organizations (name, slug) VALUES (:name, :slug) RETURNING id")
    with owner_engine.begin() as connection:
        return {
            slug: connection.execute(insert, {"name": slug.title(), "slug": slug}).scalar_one()
            for slug in ("alpha", "bravo")
        }


def _visible(connection: Connection) -> list[str]:
    return list(connection.execute(VISIBLE_SLUGS).scalars())


def test_without_tenant_context_the_runtime_role_sees_nothing(
    tenants: dict[str, uuid.UUID], app_engine: Engine
) -> None:
    with app_engine.connect() as connection:
        assert _visible(connection) == []
        assert connection.execute(text("SELECT count(*) FROM core.organizations")).scalar_one() == 0


@pytest.mark.parametrize(("own", "other"), [("alpha", "bravo"), ("bravo", "alpha")])
def test_a_tenant_sees_only_its_own_row(
    tenants: dict[str, uuid.UUID], app_engine: Engine, own: str, other: str
) -> None:
    with app_engine.begin() as connection:
        connection.execute(SET_TENANT, {"organization_id": str(tenants[own])})
        assert _visible(connection) == [own]

        # Asking for the other tenant by key or by name finds nothing: it is not an error
        # that reveals existence, the row is simply not there.
        by_id = text("SELECT count(*) FROM core.organizations WHERE id = :id")
        assert connection.execute(by_id, {"id": tenants[other]}).scalar_one() == 0
        by_slug = text("SELECT count(*) FROM core.organizations WHERE slug = :slug")
        assert connection.execute(by_slug, {"slug": other}).scalar_one() == 0


def test_tenant_context_does_not_leak_to_the_next_user_of_a_pooled_connection(
    tenants: dict[str, uuid.UUID], database: TestDatabase
) -> None:
    # One connection only, so the second transaction provably reuses the first one's.
    engine = create_engine(database.app_url, pool_size=1, max_overflow=0, hide_parameters=True)
    try:
        with engine.begin() as connection:
            first_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
            connection.execute(SET_TENANT, {"organization_id": str(tenants["alpha"])})
            assert _visible(connection) == ["alpha"]

        with engine.begin() as connection:
            assert connection.execute(text("SELECT pg_backend_pid()")).scalar_one() == first_pid
            assert _visible(connection) == []  # context ended with the transaction

            connection.execute(SET_TENANT, {"organization_id": str(tenants["bravo"])})
            assert _visible(connection) == ["bravo"]
    finally:
        engine.dispose()


def test_malformed_tenant_context_fails_closed(
    tenants: dict[str, uuid.UUID], app_engine: Engine
) -> None:
    with app_engine.connect() as connection:
        connection.execute(SET_TENANT, {"organization_id": "' OR true --"})
        with pytest.raises(DataError):
            _visible(connection)


def test_an_unknown_tenant_sees_nothing(tenants: dict[str, uuid.UUID], app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        connection.execute(SET_TENANT, {"organization_id": str(uuid.uuid4())})
        assert _visible(connection) == []


def test_the_owner_role_is_not_filtered(
    tenants: dict[str, uuid.UUID], owner_engine: Engine
) -> None:
    """Documents a known limit: the table owner bypasses the policy (no FORCE)."""
    with owner_engine.connect() as connection:
        assert _visible(connection) == ["alpha", "bravo"]
