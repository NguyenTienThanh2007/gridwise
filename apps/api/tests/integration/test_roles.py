"""The API's database role is unprivileged, and the schema is not its own."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from tests.integration.conftest import APP_ROLE, OWNER_ROLE

pytestmark = pytest.mark.integration

INSUFFICIENT_PRIVILEGE = "42501"


@pytest.fixture(autouse=True)
def _migrated(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")


def _denied(engine: Engine, statement: str) -> bool:
    try:
        with engine.begin() as connection:
            connection.execute(text(statement))
    except ProgrammingError as error:
        return getattr(error.orig, "sqlstate", None) == INSUFFICIENT_PRIVILEGE
    return False


@pytest.mark.parametrize("role", [APP_ROLE, OWNER_ROLE])
def test_application_roles_have_no_elevated_attributes(admin_engine: Engine, role: str) -> None:
    with admin_engine.connect() as connection:
        attributes = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication "
                "FROM pg_roles WHERE rolname = :role"
            ),
            {"role": role},
        ).one()
    assert tuple(attributes) == (False, False, False, False, False)


def test_each_engine_connects_as_its_intended_role(
    app_engine: Engine, owner_engine: Engine
) -> None:
    with app_engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == APP_ROLE
    with owner_engine.connect() as connection:
        assert connection.execute(text("SELECT current_user")).scalar_one() == OWNER_ROLE


def test_runtime_role_owns_no_schema_table_or_function(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        owned = connection.execute(
            text(
                """
                SELECT 'schema ' || nspname FROM pg_namespace
                 WHERE nspowner = CAST(:role AS regrole)
                UNION ALL
                SELECT 'relation ' || relname FROM pg_class
                 WHERE relowner = CAST(:role AS regrole)
                UNION ALL
                SELECT 'function ' || proname FROM pg_proc
                 WHERE proowner = CAST(:role AS regrole)
                """
            ),
            {"role": APP_ROLE},
        ).scalars()
        assert list(owned) == []

        owners = connection.execute(
            text(
                """
                SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'core'
                UNION
                SELECT pg_get_userbyid(relowner) FROM pg_class
                 WHERE relnamespace = 'core'::regnamespace
                """
            )
        ).scalars()
        assert set(owners) == {OWNER_ROLE}


def test_runtime_role_is_not_a_member_of_any_other_role(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        memberships = connection.execute(
            text("SELECT count(*) FROM pg_auth_members WHERE member = CAST(:role AS regrole)"),
            {"role": APP_ROLE},
        ).scalar_one()
    assert memberships == 0


def test_runtime_role_has_exactly_the_granted_privileges(admin_engine: Engine) -> None:
    """The whole grant list, so a new privilege cannot be added unnoticed."""
    with admin_engine.connect() as connection:
        tables = connection.execute(
            text(
                "SELECT table_schema || '.' || table_name || ':' || privilege_type "
                "FROM information_schema.role_table_grants WHERE grantee = :role ORDER BY 1"
            ),
            {"role": APP_ROLE},
        ).scalars()
        grid_tables = (
            "buses",
            "external_grids",
            "generators",
            "grids",
            "lines",
            "loads",
            "switches",
            "transformers",
        )
        assert list(tables) == [
            "core.organizations:SELECT",
            *(
                f"grid.{table}:{privilege}"
                for table in grid_tables
                for privilege in ("DELETE", "INSERT", "SELECT", "UPDATE")
            ),
            "public.alembic_version:SELECT",
            "sim.job_attempts:SELECT",
            "sim.job_transitions:SELECT",
            "sim.jobs:INSERT",
            "sim.jobs:SELECT",
            "sim.scenarios:DELETE",
            "sim.scenarios:INSERT",
            "sim.scenarios:SELECT",
            "sim.snapshots:INSERT",
            "sim.snapshots:SELECT",
        ]

        # Column-level: the API may change a job's status only to cancel it (the lifecycle
        # trigger refuses every other move for this role).
        columns = connection.execute(
            text(
                "SELECT table_schema || '.' || table_name || '.' || column_name || ':' || "
                "privilege_type FROM information_schema.role_column_grants "
                "WHERE grantee = :role AND privilege_type = 'UPDATE' "
                "AND table_schema = 'sim' ORDER BY 1"
            ),
            {"role": APP_ROLE},
        ).scalars()
        assert list(columns) == [
            "sim.jobs.cancelled_at:UPDATE",
            "sim.jobs.finished_at:UPDATE",
            "sim.jobs.status:UPDATE",
        ]

        schema_privileges = connection.execute(
            text(
                "SELECT has_schema_privilege(:role, 'core', 'USAGE'), "
                "has_schema_privilege(:role, 'core', 'CREATE'), "
                "has_schema_privilege(:role, 'public', 'CREATE'), "
                "has_schema_privilege(:role, 'grid', 'USAGE'), "
                "has_schema_privilege(:role, 'grid', 'CREATE'), "
                "has_schema_privilege(:role, 'sim', 'USAGE'), "
                "has_schema_privilege(:role, 'sim', 'CREATE')"
            ),
            {"role": APP_ROLE},
        ).one()
        assert tuple(schema_privileges) == (True, False, False, True, False, True, False)

        # Privileges that information_schema.role_table_grants would also list, stated
        # explicitly because they would defeat the design: no TRUNCATE (it ignores
        # row-level security), no REFERENCES, no TRIGGER.
        dangerous = connection.execute(
            text(
                "SELECT count(*) FROM information_schema.role_table_grants "
                "WHERE grantee = :role AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER')"
            ),
            {"role": APP_ROLE},
        ).scalar_one()
        assert dangerous == 0


def test_runtime_role_can_do_what_the_api_needs(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO core.organizations (name, slug) VALUES ('X', 'x')",
        "UPDATE core.organizations SET name = 'X'",
        "DELETE FROM core.organizations",
        "TRUNCATE core.organizations",
        "ALTER TABLE core.organizations ADD COLUMN injected text",
        "ALTER TABLE core.organizations DISABLE ROW LEVEL SECURITY",
        "DROP TABLE core.organizations",
        "DROP POLICY organization_is_current_tenant ON core.organizations",
        "CREATE TABLE core.sneaky (id int)",
        "CREATE TABLE grid.sneaky (id int)",
        "CREATE TABLE sim.sneaky (id int)",
        "TRUNCATE sim.snapshots",
        "DROP TRIGGER lifecycle ON sim.jobs",
        "ALTER TABLE sim.jobs DISABLE TRIGGER lifecycle",
        "ALTER TABLE sim.snapshots DISABLE ROW LEVEL SECURITY",
        "DROP POLICY tenant_isolation ON sim.jobs",
        "UPDATE sim.snapshots SET element_count = 0",
        "DELETE FROM sim.snapshots",
        "DELETE FROM sim.jobs",
        "UPDATE sim.jobs SET worker_id = 'me'",
        "TRUNCATE grid.grids CASCADE",
        "TRUNCATE grid.buses CASCADE",
        "ALTER TABLE grid.grids DISABLE ROW LEVEL SECURITY",
        "ALTER TABLE grid.loads ADD COLUMN injected text",
        "DROP POLICY tenant_isolation ON grid.grids",
        "CREATE POLICY open_door ON grid.grids USING (true)",
        "DROP TABLE grid.switches",
        "DROP SCHEMA grid CASCADE",
        "ALTER TABLE grid.grids DROP CONSTRAINT ck_grids_data_origin_synthetic",
        "CREATE TABLE public.sneaky (id int)",
        "CREATE SCHEMA sneaky",
        "UPDATE alembic_version SET version_num = '9999'",
        f"SET ROLE {OWNER_ROLE}",
        "CREATE ROLE sneaky",
        "COPY core.organizations TO PROGRAM 'true'",
    ],
)
def test_runtime_role_is_denied_everything_else(app_engine: Engine, statement: str) -> None:
    assert _denied(app_engine, statement), f"expected insufficient privilege for: {statement}"


def test_timescaledb_telemetry_is_disabled(admin_engine: Engine) -> None:
    with admin_engine.connect() as connection:
        assert connection.execute(text("SHOW timescaledb.telemetry_level")).scalar_one() == "off"
