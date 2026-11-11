"""Integration fixtures: every test gets its own throwaway database.

Three roles are involved, exactly as in a real deployment (docs/decisions/0006):

* ``admin``  the bootstrap superuser. Used only here, to create and drop databases.
* ``owner``  runs migrations and owns the schema.
* ``app``    the API's runtime role.

The configured development database itself is never migrated or modified.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic.config import Config
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url

API_ROOT = Path(__file__).resolve().parents[2]
REPO_ENV_FILE = API_ROOT.parents[1] / ".env"

OWNER_ROLE = "gridwise_owner"
APP_ROLE = "gridwise_app"


class IntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRIDWISE_", env_file=REPO_ENV_FILE, extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr
    migration_database_url: SecretStr
    test_admin_database_url: SecretStr


@dataclass(frozen=True)
class TestDatabase:
    """Connection URLs for one throwaway database, one per role.

    ``repr`` is suppressed so a failing assertion can never print a password.
    """

    __test__ = False  # not a test class, despite the name

    name: str
    admin_url: str
    owner_url: str
    app_url: str

    def __repr__(self) -> str:
        return f"TestDatabase(name={self.name!r})"


def _for_database(url: SecretStr, name: str) -> str:
    return make_url(url.get_secret_value()).set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def integration_settings() -> IntegrationSettings:
    return IntegrationSettings()


@pytest.fixture
def database(integration_settings: IntegrationSettings) -> Iterator[TestDatabase]:
    name = f"gridwise_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(
        integration_settings.test_admin_database_url.get_secret_value(),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}" OWNER {OWNER_ROLE}'))
        yield TestDatabase(
            name=name,
            admin_url=_for_database(integration_settings.test_admin_database_url, name),
            owner_url=_for_database(integration_settings.migration_database_url, name),
            app_url=_for_database(integration_settings.database_url, name),
        )
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _engine(url: str) -> Iterator[Engine]:
    engine = create_engine(url, hide_parameters=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def alembic_config(database: TestDatabase) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.attributes["database_url"] = database.owner_url
    config.attributes["configure_logging"] = False
    return config


@pytest.fixture
def owner_engine(database: TestDatabase) -> Iterator[Engine]:
    yield from _engine(database.owner_url)


@pytest.fixture
def app_engine(database: TestDatabase) -> Iterator[Engine]:
    yield from _engine(database.app_url)


@pytest.fixture
def admin_engine(database: TestDatabase) -> Iterator[Engine]:
    yield from _engine(database.admin_url)
