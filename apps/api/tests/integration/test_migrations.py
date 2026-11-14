import time

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from gridwise_api.models import Base
from gridwise_api.models.base import include_managed_names
from tests.integration.conftest import TestDatabase

pytestmark = pytest.mark.integration

INSERT_ORG = text("INSERT INTO core.organizations (name, slug) VALUES (:name, :slug) RETURNING id")


GRID_TABLES = [
    "buses",
    "external_grids",
    "generators",
    "grids",
    "lines",
    "loads",
    "switches",
    "transformers",
]


def _grid_tables(engine: Engine) -> list[str] | None:
    """Sorted table names of the grid schema, or None if the schema does not exist."""
    inspector = inspect(engine)
    if "grid" not in inspector.get_schema_names():
        return None
    return sorted(inspector.get_table_names(schema="grid"))


def _grid_leftovers(engine: Engine) -> list[str]:
    """Anything a downgrade should have removed: policies, and the runtime role's access."""
    with engine.connect() as connection:
        policies = connection.execute(
            text("SELECT policyname FROM pg_policies WHERE schemaname = 'grid'")
        ).scalars()
        grants = connection.execute(
            text(
                "SELECT table_name FROM information_schema.role_table_grants "
                "WHERE grantee = 'gridwise_app' AND table_schema = 'grid'"
            )
        ).scalars()
        return [*policies, *grants]


def _core_objects(engine: Engine) -> dict[str, list[str]]:
    inspector = inspect(engine)
    if "core" not in inspector.get_schema_names():
        return {}
    with engine.connect() as connection:
        functions = connection.execute(
            text(
                "SELECT proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'core' ORDER BY proname"
            )
        ).scalars()
        return {"tables": inspector.get_table_names(schema="core"), "functions": list(functions)}


def test_upgrade_downgrade_upgrade_round_trip(alembic_config: Config, owner_engine: Engine) -> None:
    expected = {
        "tables": ["organizations"],
        "functions": ["current_organization_id", "set_updated_at"],
    }
    command.upgrade(alembic_config, "head")
    assert _core_objects(owner_engine) == expected
    assert _grid_tables(owner_engine) == GRID_TABLES

    # One step back: the grid schema is gone completely, the baseline is intact.
    command.downgrade(alembic_config, "0001")
    assert _grid_tables(owner_engine) is None
    assert _grid_leftovers(owner_engine) == []
    assert _core_objects(owner_engine) == expected

    command.upgrade(alembic_config, "head")
    assert _grid_tables(owner_engine) == GRID_TABLES

    command.downgrade(alembic_config, "base")
    assert _core_objects(owner_engine) == {}
    assert _grid_tables(owner_engine) is None

    command.upgrade(alembic_config, "head")
    assert _core_objects(owner_engine) == expected
    assert _grid_tables(owner_engine) == GRID_TABLES


def test_a_downgrade_with_data_removes_the_data_and_upgrades_cleanly(
    alembic_config: Config, owner_engine: Engine
) -> None:
    command.upgrade(alembic_config, "head")
    with owner_engine.begin() as connection:
        organization = connection.execute(INSERT_ORG, {"name": "Demo", "slug": "demo"}).scalar_one()
        grid = connection.execute(
            text(
                "INSERT INTO grid.grids (organization_id, name, frequency_hz, topology_hash) "
                "VALUES (:organization, 'G', 50, :hash) RETURNING id"
            ),
            {"organization": organization, "hash": "0" * 64},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO grid.buses (organization_id, grid_id, key, name, nominal_voltage_kv) "
                "VALUES (:organization, :grid, 'a', 'A', 20)"
            ),
            {"organization": organization, "grid": grid},
        )

    command.downgrade(alembic_config, "0001")
    assert _grid_tables(owner_engine) is None
    with owner_engine.connect() as connection:  # the tenant itself is untouched
        assert connection.execute(text("SELECT count(*) FROM core.organizations")).scalar_one() == 1

    command.upgrade(alembic_config, "head")
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM grid.grids")).scalar_one() == 0


def test_the_api_expects_the_head_revision(alembic_config: Config) -> None:
    from gridwise_api.schema_version import EXPECTED_SCHEMA_REVISION

    assert ScriptDirectory.from_config(alembic_config).get_current_head() == "0005"
    assert EXPECTED_SCHEMA_REVISION == "0005"


def test_migrations_cannot_be_run_by_the_runtime_role(
    alembic_config: Config, database: TestDatabase, owner_engine: Engine
) -> None:
    """gridwise_app may not create anything, so a migration run with its credentials fails
    and leaves the database as it was. From the baseline: nothing at all is created."""
    alembic_config.attributes["database_url"] = database.app_url
    with pytest.raises(ProgrammingError, match="permission denied"):
        command.upgrade(alembic_config, "head")
    assert _core_objects(owner_engine) == {}
    assert _grid_tables(owner_engine) is None


def test_the_runtime_role_cannot_apply_the_grid_migration_either(
    alembic_config: Config, database: TestDatabase, owner_engine: Engine
) -> None:
    command.upgrade(alembic_config, "0001")  # as the owner
    alembic_config.attributes["database_url"] = database.app_url
    with pytest.raises(ProgrammingError, match="permission denied"):
        command.upgrade(alembic_config, "head")
    assert _grid_tables(owner_engine) is None
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0001"
        )


def test_there_is_exactly_one_migration_head(alembic_config: Config) -> None:
    assert len(ScriptDirectory.from_config(alembic_config).get_heads()) == 1


def test_models_match_the_migrated_schema(alembic_config: Config, owner_engine: Engine) -> None:
    """Fails when a model changes without a migration (or the reverse)."""
    command.upgrade(alembic_config, "head")
    with owner_engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_name": include_managed_names,
                "compare_server_default": True,
            },
        )
        differences = compare_metadata(context, Base.metadata)
    assert differences == []


def test_organization_constraints(alembic_config: Config, owner_engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    with owner_engine.begin() as connection:
        first = connection.execute(INSERT_ORG, {"name": "Demo Utility", "slug": "demo-utility"})
        second = connection.execute(INSERT_ORG, {"name": "Other Utility", "slug": "other"})
        first_id, second_id = first.scalar_one(), second.scalar_one()
        assert first_id.version == 7
        assert first_id < second_id  # UUIDv7 keys are time-ordered

    for bad in (
        {"name": "Duplicate", "slug": "demo-utility"},
        {"name": "Bad Slug", "slug": "Not A Slug"},
        {"name": "   ", "slug": "blank-name"},
    ):
        with pytest.raises(IntegrityError), owner_engine.begin() as connection:
            connection.execute(INSERT_ORG, bad)


def test_updated_at_is_maintained_by_the_database(
    alembic_config: Config, owner_engine: Engine
) -> None:
    command.upgrade(alembic_config, "head")
    select = text("SELECT created_at, updated_at FROM core.organizations WHERE slug = 'demo'")

    with owner_engine.begin() as connection:
        connection.execute(INSERT_ORG, {"name": "Demo", "slug": "demo"})
    with owner_engine.connect() as connection:
        created_at, initial = connection.execute(select).one()
    assert initial == created_at

    time.sleep(0.01)
    with owner_engine.begin() as connection:
        connection.execute(
            text("UPDATE core.organizations SET name = 'Renamed' WHERE slug = 'demo'")
        )
    with owner_engine.connect() as connection:
        created_after, after_rename = connection.execute(select).one()
    assert created_after == created_at
    assert after_rename > initial

    # A writer cannot backdate it either: the trigger overrides the supplied value.
    with owner_engine.begin() as connection:
        connection.execute(
            text("UPDATE core.organizations SET updated_at = '2000-01-01Z' WHERE slug = 'demo'")
        )
    with owner_engine.connect() as connection:
        _, after_backdate = connection.execute(select).one()
    assert after_backdate > after_rename


def test_migrations_refuse_to_run_as_a_superuser(
    alembic_config: Config, database: TestDatabase, admin_engine: Engine
) -> None:
    alembic_config.attributes["database_url"] = database.admin_url
    with pytest.raises(RuntimeError, match="superuser"):
        command.upgrade(alembic_config, "head")
    assert "core" not in inspect(admin_engine).get_schema_names()


async def test_the_sim_schema_downgrades_with_data_and_upgrades_again(
    alembic_config: Config, owner_engine: Engine, database: TestDatabase
) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from tests.support.simulations import service, stored_grid

    command.upgrade(alembic_config, "head")
    with owner_engine.begin() as connection:
        organization = connection.execute(INSERT_ORG, {"name": "Demo", "slug": "demo"}).scalar_one()
    engine = create_async_engine(database.app_url)
    try:
        grid_id = await stored_grid(engine, organization)
        await service(engine).submit(organization, grid_id)
    finally:
        await engine.dispose()

    command.downgrade(alembic_config, "0003")
    with owner_engine.connect() as connection:  # the worker layer is gone, the job is kept
        assert connection.execute(text("SELECT count(*) FROM sim.jobs")).scalar_one() == 1
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'sim' AND p.proname LIKE '%_job'"
                )
            ).scalar_one()
            == 0
        )
    command.downgrade(alembic_config, "0002")
    inspector = inspect(owner_engine)
    assert "sim" not in inspector.get_schema_names()
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM grid.grids")).scalar_one() == 1
        functions = connection.execute(
            text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'sim'"
            )
        ).scalar_one()
    assert functions == 0

    command.upgrade(alembic_config, "head")
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM sim.jobs")).scalar_one() == 0
        assert (
            connection.execute(text("SELECT count(*) FROM sim.job_transitions")).scalar_one() == 6
        )
