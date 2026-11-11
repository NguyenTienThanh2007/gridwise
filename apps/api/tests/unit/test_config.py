import pytest
from pydantic import ValidationError

from gridwise_api.config import MigrationSettings, Settings

VALID_URL = "postgresql+psycopg://user:s3cret-value@localhost:5432/db"


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRIDWISE_DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_database_url_must_use_psycopg_driver() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="postgresql://user:s3cret-value@localhost/db")
    assert "s3cret-value" not in str(error.value)


def test_database_password_is_not_exposed_by_repr() -> None:
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert "s3cret-value" not in repr(settings)
    assert settings.database_url.get_secret_value() == VALID_URL


def test_settings_are_read_from_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRIDWISE_DATABASE_URL", VALID_URL)
    monkeypatch.setenv("GRIDWISE_ENVIRONMENT", "staging")
    monkeypatch.setenv("GRIDWISE_CORS_ORIGINS", '["https://app.example.test"]')
    settings = Settings(_env_file=None)
    assert settings.environment == "staging"
    assert settings.cors_origins == ["https://app.example.test"]


def test_wildcard_cors_origin_is_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit origins"):
        Settings(_env_file=None, database_url=VALID_URL, cors_origins=["*"])


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=VALID_URL, environment="prod")


def test_api_settings_do_not_require_or_expose_the_migration_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GRIDWISE_MIGRATION_DATABASE_URL", VALID_URL.replace("user", "owner"))
    settings = Settings(_env_file=None, database_url=VALID_URL)
    assert not hasattr(settings, "migration_database_url")
    assert "owner" not in repr(settings)


def test_migration_settings_require_their_own_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRIDWISE_MIGRATION_DATABASE_URL", raising=False)
    monkeypatch.setenv("GRIDWISE_DATABASE_URL", VALID_URL)  # the runtime URL is not a fallback
    with pytest.raises(ValidationError, match="migration_database_url"):
        MigrationSettings(_env_file=None)


def test_migration_url_is_validated_without_leaking_it() -> None:
    with pytest.raises(ValidationError) as error:
        MigrationSettings(
            _env_file=None, migration_database_url="postgresql://owner:s3cret-value@localhost/db"
        )
    assert "s3cret-value" not in str(error.value)
    settings = MigrationSettings(_env_file=None, migration_database_url=VALID_URL)
    assert "s3cret-value" not in repr(settings)
