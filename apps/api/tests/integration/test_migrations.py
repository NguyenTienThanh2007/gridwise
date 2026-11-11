import time

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

from gridwise_api.models import Base
from gridwise_api.models.base import include_managed_names
from tests.integration.conftest import TestDatabase

pytestmark = pytest.mark.integration

INSERT_ORG = text("INSERT INTO core.organizations (name, slug) VALUES (:name, :slug) RETURNING id")


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

    command.downgrade(alembic_config, "base")
    assert _core_objects(owner_engine) == {}

    command.upgrade(alembic_config, "head")
    assert _core_objects(owner_engine) == expected


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
