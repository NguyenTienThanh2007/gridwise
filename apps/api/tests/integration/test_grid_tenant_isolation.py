"""Row-level security on the grid schema, through the runtime role.

Two organisations each own a grid with every element type. The tests show, for all eight
tables: nothing is visible without tenant context, a tenant sees only its own rows, and it
cannot create, change, delete or reference another tenant's rows.

What this proves: the database isolates tenants for the runtime role when the application
sets tenant context through ``tenant_transaction``. What it does not prove: that GRIDWISE
is access-controlled. There is no authentication yet (P6); the only tenant the application
can act for is the fixed development tenant, in local and test environments.
"""

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import grids
from gridwise_api.tenancy import tenant_transaction
from tests.support.grids import GRID_TABLES, sample_grid

pytestmark = pytest.mark.integration

ELEMENT_TABLES = GRID_TABLES[1:]
ROW_LEVEL_SECURITY_VIOLATION = "42501"
FOREIGN_KEY_VIOLATION = "23503"


@dataclass(frozen=True)
class Tenant:
    organization_id: uuid.UUID
    grid_id: uuid.UUID


@pytest.fixture
async def world(tenants: dict[str, uuid.UUID], app_async_engine: AsyncEngine) -> dict[str, Tenant]:
    """Each tenant creates its own grid as the runtime role, under its own context."""
    created = {}
    for slug, organization_id in tenants.items():
        async with tenant_transaction(app_async_engine, organization_id) as session:
            record = await grids.create_grid(session, sample_grid(f"{slug} grid (synthetic)"))
        created[slug] = Tenant(organization_id, record.id)
    return created


def _count(table: str) -> str:
    return f"SELECT count(*) FROM grid.{table}"  # noqa: S608  (table names are constants)


async def _counts(session: object) -> dict[str, int]:
    return {
        table: (await session.execute(text(_count(table)))).scalar_one()  # type: ignore[attr-defined]
        for table in GRID_TABLES
    }


EXPECTED_ROWS = {
    "grids": 1,
    "buses": 5,
    "lines": 2,
    "transformers": 1,
    "loads": 2,
    "generators": 2,
    "external_grids": 1,
    "switches": 3,
}


async def test_without_tenant_context_no_table_shows_a_row(
    world: dict[str, Tenant], app_async_engine: AsyncEngine
) -> None:
    async with app_async_engine.connect() as connection:
        assert await _counts(connection) == dict.fromkeys(GRID_TABLES, 0)


def test_the_rows_do_exist(world: dict[str, Tenant], owner_engine: Engine) -> None:
    """The control for the test above: seen by the owner, both tenants' rows are there."""
    with owner_engine.connect() as connection:
        for table in GRID_TABLES:
            assert connection.execute(text(_count(table))).scalar_one() == 2 * EXPECTED_ROWS[table]


@pytest.mark.parametrize(("own", "other"), [("alpha", "bravo"), ("bravo", "alpha")])
async def test_a_tenant_sees_exactly_its_own_rows_in_every_table(
    world: dict[str, Tenant], app_async_engine: AsyncEngine, own: str, other: str
) -> None:
    async with tenant_transaction(app_async_engine, world[own].organization_id) as session:
        assert await _counts(session) == EXPECTED_ROWS
        for table in GRID_TABLES:
            foreign = await session.execute(
                text(f"{_count(table)} WHERE organization_id = :other"),
                {"other": world[other].organization_id},
            )
            assert foreign.scalar_one() == 0
        for table in ELEMENT_TABLES:
            by_grid = await session.execute(
                text(f"{_count(table)} WHERE grid_id = :grid"), {"grid": world[other].grid_id}
            )
            assert by_grid.scalar_one() == 0

        assert await grids.get_grid(session, world[other].grid_id) is None
        assert await grids.load_grid(session, world[other].grid_id) is None
        assert (await grids.get_grid(session, world[own].grid_id)) is not None


async def test_an_unknown_tenant_sees_nothing(
    world: dict[str, Tenant], app_async_engine: AsyncEngine
) -> None:
    async with tenant_transaction(app_async_engine, uuid.uuid4()) as session:
        assert await _counts(session) == dict.fromkeys(GRID_TABLES, 0)


@pytest.mark.parametrize("table", GRID_TABLES)
async def test_a_tenant_cannot_change_or_delete_another_tenants_rows(
    world: dict[str, Tenant], app_async_engine: AsyncEngine, owner_engine: Engine, table: str
) -> None:
    """The statements succeed and touch nothing: the rows are simply not there."""
    other = world["bravo"].organization_id
    async with tenant_transaction(app_async_engine, world["alpha"].organization_id) as session:
        updated = await session.execute(
            text(f"UPDATE grid.{table} SET name = 'taken over' WHERE organization_id = :other"),  # noqa: S608
            {"other": other},
        )
        deleted = await session.execute(
            text(f"DELETE FROM grid.{table} WHERE organization_id = :other"),  # noqa: S608
            {"other": other},
        )
        assert (updated.rowcount, deleted.rowcount) == (0, 0)

    with owner_engine.connect() as connection:
        untouched = connection.execute(
            text(
                f"SELECT count(*) FILTER (WHERE name <> 'taken over') FROM grid.{table} "  # noqa: S608
                "WHERE organization_id = :other"
            ),
            {"other": other},
        ).scalar_one()
    assert untouched == EXPECTED_ROWS[table]


async def test_a_tenant_cannot_delete_another_tenants_grid_through_the_repository(
    world: dict[str, Tenant], app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    async with tenant_transaction(app_async_engine, world["alpha"].organization_id) as session:
        assert await grids.delete_grid(session, world["bravo"].grid_id) is False
        with pytest.raises(grids.GridVersionConflictError):
            await grids.claim_version(session, world["bravo"].grid_id, 1)

    with owner_engine.connect() as connection:
        version = connection.execute(
            text("SELECT version FROM grid.grids WHERE id = :id"), {"id": world["bravo"].grid_id}
        ).scalar_one()
    assert version == 1


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


async def test_a_tenant_cannot_create_a_grid_for_another_tenant(
    world: dict[str, Tenant], app_async_engine: AsyncEngine
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with tenant_transaction(app_async_engine, world["alpha"].organization_id) as session:
            await session.execute(
                text(
                    "INSERT INTO grid.grids (organization_id, name, frequency_hz, topology_hash) "
                    "VALUES (:organization_id, 'planted', 50, :hash)"
                ),
                {"organization_id": world["bravo"].organization_id, "hash": "0" * 64},
            )
    assert _sqlstate(raised.value) == ROW_LEVEL_SECURITY_VIOLATION


async def test_a_tenant_cannot_create_a_grid_without_context(
    world: dict[str, Tenant], app_async_engine: AsyncEngine
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with app_async_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO grid.grids (organization_id, name, frequency_hz, topology_hash) "
                    "VALUES (:organization_id, 'planted', 50, :hash)"
                ),
                {"organization_id": world["alpha"].organization_id, "hash": "0" * 64},
            )
    assert _sqlstate(raised.value) == ROW_LEVEL_SECURITY_VIOLATION


async def test_a_tenant_cannot_move_its_row_to_another_tenant(
    world: dict[str, Tenant], app_async_engine: AsyncEngine
) -> None:
    with pytest.raises(DBAPIError) as raised:
        async with tenant_transaction(app_async_engine, world["alpha"].organization_id) as session:
            await session.execute(
                text("UPDATE grid.grids SET organization_id = :other WHERE id = :id"),
                {"other": world["bravo"].organization_id, "id": world["alpha"].grid_id},
            )
    # Refused by the policy's WITH CHECK, or earlier by the children's foreign keys.
    assert _sqlstate(raised.value) in (ROW_LEVEL_SECURITY_VIOLATION, FOREIGN_KEY_VIOLATION)


INSERT_BUS = text(
    "INSERT INTO grid.buses (organization_id, grid_id, key, name, nominal_voltage_kv) "
    "VALUES (:organization_id, :grid_id, 'planted', 'Planted', 20)"
)


async def test_a_tenant_cannot_add_an_element_to_another_tenants_grid(
    world: dict[str, Tenant], app_async_engine: AsyncEngine
) -> None:
    alpha, bravo = world["alpha"], world["bravo"]

    # Claiming the row as its own: the composite foreign key finds no such grid.
    with pytest.raises(IntegrityError) as as_own:
        async with tenant_transaction(app_async_engine, alpha.organization_id) as session:
            await session.execute(
                INSERT_BUS, {"organization_id": alpha.organization_id, "grid_id": bravo.grid_id}
            )
    assert _sqlstate(as_own.value) == FOREIGN_KEY_VIOLATION

    # Writing it for the other tenant: refused by the policy.
    with pytest.raises(DBAPIError) as as_other:
        async with tenant_transaction(app_async_engine, alpha.organization_id) as session:
            await session.execute(
                INSERT_BUS, {"organization_id": bravo.organization_id, "grid_id": bravo.grid_id}
            )
    assert _sqlstate(as_other.value) == ROW_LEVEL_SECURITY_VIOLATION


@pytest.mark.parametrize("table", ELEMENT_TABLES)
@pytest.mark.parametrize("existing", [True, False], ids=["existing-key", "unknown-key"])
async def test_constraint_errors_do_not_reveal_another_tenants_keys(
    world: dict[str, Tenant],
    app_async_engine: AsyncEngine,
    owner_engine: Engine,
    table: str,
    existing: bool,
) -> None:
    """Probing another tenant's grid gives the same error whether a key exists there or not.

    Uniqueness is checked when a row is inserted, foreign keys afterwards. If the unique
    constraint did not include organization_id, a key that exists in the other grid would
    produce "duplicate key" and an unknown one "foreign key": an oracle for the other
    tenant's element keys.
    """
    alpha, bravo = world["alpha"], world["bravo"]
    with owner_engine.connect() as connection:
        known = (
            connection.execute(
                text(f"SELECT * FROM grid.{table} WHERE grid_id = :grid LIMIT 1"),  # noqa: S608
                {"grid": bravo.grid_id},
            )
            .mappings()
            .one()
        )
    row = {
        column: value
        for column, value in known.items()
        if column not in ("id", "created_at", "updated_at")
    }
    row.update(
        organization_id=alpha.organization_id,
        key=known["key"] if existing else "no-such-key",
    )
    columns = ", ".join(row)
    placeholders = ", ".join(f":{column}" for column in row)
    with pytest.raises(DBAPIError) as raised:
        async with tenant_transaction(app_async_engine, alpha.organization_id) as session:
            await session.execute(
                text(f"INSERT INTO grid.{table} ({columns}) VALUES ({placeholders})"),  # noqa: S608
                row,
            )
    assert _sqlstate(raised.value) == FOREIGN_KEY_VIOLATION


def _bus_id(engine: Engine, grid_id: uuid.UUID, key: str) -> uuid.UUID:
    with engine.connect() as connection:
        return connection.execute(  # type: ignore[no-any-return]
            text("SELECT id FROM grid.buses WHERE grid_id = :grid_id AND key = :key"),
            {"grid_id": grid_id, "key": key},
        ).scalar_one()


async def test_an_element_cannot_reference_a_bus_of_another_tenant(
    world: dict[str, Tenant], app_async_engine: AsyncEngine, owner_engine: Engine
) -> None:
    """Even knowing the other tenant's bus id, a load cannot be attached to it."""
    alpha, bravo = world["alpha"], world["bravo"]
    foreign_bus = _bus_id(owner_engine, bravo.grid_id, "b")
    with pytest.raises(IntegrityError) as raised:
        async with tenant_transaction(app_async_engine, alpha.organization_id) as session:
            await session.execute(
                text(
                    "INSERT INTO grid.loads (organization_id, grid_id, key, name, bus_id, p_mw, "
                    "q_mvar) VALUES (:organization_id, :grid_id, 'planted', 'Planted', :bus, 1, 0)"
                ),
                {
                    "organization_id": alpha.organization_id,
                    "grid_id": alpha.grid_id,
                    "bus": foreign_bus,
                },
            )
    assert _sqlstate(raised.value) == FOREIGN_KEY_VIOLATION


def test_the_owner_cannot_cross_grids_or_tenants_either(
    world: dict[str, Tenant], owner_engine: Engine
) -> None:
    """The composite keys hold for every role, including one that bypasses the policies."""
    alpha, bravo = world["alpha"], world["bravo"]
    foreign_bus = _bus_id(owner_engine, bravo.grid_id, "b")
    own_bus = _bus_id(owner_engine, alpha.grid_id, "b")
    cases = [
        # another tenant's bus
        ("UPDATE grid.loads SET bus_id = :bus WHERE grid_id = :grid", foreign_bus),
        (
            "UPDATE grid.lines SET to_bus_id = :bus WHERE grid_id = :grid AND key = 'ab'",
            foreign_bus,
        ),
        (
            "UPDATE grid.switches SET other_bus_id = :bus "
            "WHERE grid_id = :grid AND key = 'coupler'",
            foreign_bus,
        ),
    ]
    for statement, bus in cases:
        with pytest.raises(IntegrityError), owner_engine.begin() as connection:
            connection.execute(text(statement), {"bus": bus, "grid": alpha.grid_id})

    # A second grid of the same tenant: its buses are out of reach too.
    with owner_engine.begin() as connection:
        second = connection.execute(
            text(
                "INSERT INTO grid.grids (organization_id, name, frequency_hz, topology_hash) "
                "VALUES (:organization_id, 'second', 50, :hash) RETURNING id"
            ),
            {"organization_id": alpha.organization_id, "hash": "0" * 64},
        ).scalar_one()
    with pytest.raises(IntegrityError), owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO grid.loads (organization_id, grid_id, key, name, bus_id, p_mw, q_mvar)"
                " VALUES (:organization_id, :grid_id, 'x', 'X', :bus, 1, 0)"
            ),
            {"organization_id": alpha.organization_id, "grid_id": second, "bus": own_bus},
        )


def test_every_grid_table_has_row_level_security_and_one_policy_for_the_runtime_role(
    migrated: None, admin_engine: Engine
) -> None:
    with admin_engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'grid' AND c.relkind = 'r'"
            )
        ).all()
        enabled = {row.relname: row.relrowsecurity for row in tables}
        policies = connection.execute(
            text(
                "SELECT tablename, policyname, cmd, roles::text, qual, with_check "
                "FROM pg_policies WHERE schemaname = 'grid' ORDER BY tablename"
            )
        ).all()
    assert enabled == dict.fromkeys(GRID_TABLES, True)
    condition = "(organization_id = core.current_organization_id())"
    assert [tuple(row) for row in policies] == [
        (table, "tenant_isolation", "ALL", "{gridwise_app}", condition, condition)
        for table in sorted(GRID_TABLES)
    ]
