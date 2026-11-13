"""The development tenant exists only where it is allowed and asked for."""

import uuid

import pytest
from pydantic import ValidationError

from gridwise_api.config import DEVELOPMENT_ENVIRONMENTS, SeedSettings, Settings
from gridwise_api.seed import SeedRefusedError, require_development_environment
from gridwise_api.tenancy import (
    DevelopmentTenantUnavailableError,
    TenantSession,
    resolve_development_tenant,
    tenant_transaction,
)

VALID_URL = "postgresql+psycopg://user:s3cret-value@localhost:5432/db"
TENANT = uuid.UUID("d0000000-0000-4000-8000-000000000001")


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, database_url=VALID_URL, **values)  # type: ignore[arg-type]


def test_only_local_and_test_are_development_environments() -> None:
    assert frozenset({"local", "test"}) == DEVELOPMENT_ENVIRONMENTS


@pytest.mark.parametrize("environment", ["local", "test"])
def test_the_development_tenant_is_available_when_configured(environment: str) -> None:
    settings = _settings(environment=environment, dev_organization_id=TENANT)
    assert resolve_development_tenant(settings) == TENANT


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_configuration_refuses_a_development_tenant_elsewhere(environment: str) -> None:
    with pytest.raises(ValidationError, match="dev_organization_id must not be set"):
        _settings(environment=environment, dev_organization_id=TENANT)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_refusal_also_applies_to_values_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("GRIDWISE_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("GRIDWISE_ENVIRONMENT", environment)
    monkeypatch.setenv("GRIDWISE_DEV_ORGANIZATION_ID", str(TENANT))
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("environment", ["local", "test", "staging", "production"])
def test_without_the_setting_there_is_no_development_tenant_anywhere(environment: str) -> None:
    """The environment defaults to "local", so the environment alone must never be enough."""
    settings = _settings(environment=environment)
    assert settings.dev_organization_id is None
    with pytest.raises(DevelopmentTenantUnavailableError):
        resolve_development_tenant(settings)


def test_an_unconfigured_deployment_has_no_development_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("GRIDWISE_ENVIRONMENT", "GRIDWISE_DEV_ORGANIZATION_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GRIDWISE_DATABASE_URL", VALID_URL)
    settings = Settings(_env_file=None)
    assert settings.environment == "local"  # the default that makes the second key necessary
    with pytest.raises(DevelopmentTenantUnavailableError):
        resolve_development_tenant(settings)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_the_resolver_checks_the_environment_itself(environment: str) -> None:
    """Defence in depth: even a settings object that slipped past validation is refused."""
    settings = _settings(environment="local", dev_organization_id=TENANT)
    forged = settings.model_copy(update={"environment": environment})
    assert forged.dev_organization_id == TENANT
    with pytest.raises(DevelopmentTenantUnavailableError, match="local and test"):
        resolve_development_tenant(forged)


@pytest.mark.parametrize("bad", ["not-a-uuid", "1234", "d0000000-0000"])
def test_a_malformed_development_tenant_is_rejected_without_echoing_it(bad: str) -> None:
    with pytest.raises(ValidationError) as raised:
        _settings(dev_organization_id=bad)
    assert "s3cret-value" not in str(raised.value)


def test_the_development_tenant_is_not_exposed_by_the_system_endpoint_model() -> None:
    from gridwise_api.api.routes.system import SystemInfo

    assert "dev_organization_id" not in SystemInfo.model_fields


@pytest.mark.parametrize("environment", ["local", "test"])
def test_seeding_is_allowed_in_development_environments(environment: str) -> None:
    require_development_environment(environment)


@pytest.mark.parametrize("environment", ["staging", "production", "", "Local", "prod"])
def test_seeding_is_refused_everywhere_else(environment: str) -> None:
    with pytest.raises(SeedRefusedError):
        require_development_environment(environment)


def test_seed_settings_require_an_explicit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRIDWISE_ENVIRONMENT", raising=False)
    monkeypatch.setenv("GRIDWISE_MIGRATION_DATABASE_URL", VALID_URL)
    with pytest.raises(ValidationError, match="environment"):
        SeedSettings(_env_file=None)


def test_seed_settings_cannot_see_the_api_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDWISE_MIGRATION_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("GRIDWISE_DATABASE_URL", VALID_URL.replace("user", "app"))
    monkeypatch.setenv("GRIDWISE_ENVIRONMENT", "local")
    settings = SeedSettings(_env_file=None)
    assert not hasattr(settings, "database_url")
    assert "s3cret-value" not in repr(settings)


def test_a_tenant_session_cannot_be_constructed_directly() -> None:
    with pytest.raises(TypeError, match="tenant_transaction"):
        TenantSession(object(), TENANT, object())  # type: ignore[arg-type]


async def test_a_tenant_transaction_needs_a_uuid_before_it_touches_the_database() -> None:
    class NoDatabase:
        def begin(self) -> None:
            raise AssertionError("the engine must not be used")

    with pytest.raises(TypeError, match="UUID"):
        async with tenant_transaction(NoDatabase(), str(TENANT)):  # type: ignore[arg-type]
            pass


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_setting_means_not_configured(empty: str) -> None:
    """Docker Compose passes an unset variable as an empty string; the API must still start."""
    settings = _settings(environment="production", dev_organization_id=empty)
    assert settings.dev_organization_id is None
