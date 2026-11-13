"""Centralised, validated configuration. Nothing else reads the environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root when running from a checkout; simply absent in a container image.
_REPO_ENV_FILE = Path(__file__).resolve().parents[4] / ".env"

DATABASE_URL_SCHEME = "postgresql+psycopg://"

type Environment = Literal["local", "test", "staging", "production"]

#: The only environments in which development-only mechanisms may exist: the fixed
#: development tenant and the synthetic demonstration data.
DEVELOPMENT_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test"})


def _require_psycopg_url(value: SecretStr, field_name: str) -> SecretStr:
    if not value.get_secret_value().startswith(DATABASE_URL_SCHEME):
        # Never echo the value: it contains a password.
        raise ValueError(f"{field_name} must start with {DATABASE_URL_SCHEME}")
    return value


class LoggingSettings(BaseSettings):
    """Shared by the API and the migration runner."""

    model_config = SettingsConfigDict(
        env_prefix="GRIDWISE_",
        env_file=_REPO_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # Validation errors must never echo a value: several fields hold secrets.
        hide_input_in_errors=True,
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"


class Settings(LoggingSettings):
    """API runtime configuration."""

    environment: Environment = "local"

    # Credentials of the *runtime* role (gridwise_app): no superuser, no BYPASSRLS, owns
    # nothing. Required on purpose: there is no credential default in code.
    database_url: SecretStr
    database_pool_size: int = Field(default=5, ge=1, le=50)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)

    cors_origins: list[str] = Field(default_factory=list)

    # Host names the API answers to (the Host header, without the port). Anything else is
    # refused: without authentication, this is what stops a web page that rebinds its own
    # domain to 127.0.0.1 from reaching the API (decision 0009).
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"], min_length=1
    )

    # Limits of the grid API. CIGRE MV, the demonstration network, has 68 elements.
    grid_max_elements: int = Field(default=5000, ge=1, le=100_000)
    max_request_body_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)

    # The fixed development tenant (docs/decisions/0008). There is no authentication before
    # P6, so tenant-scoped code can only run for one organisation chosen by the operator.
    # No default, on purpose: `environment` defaults to "local", so the environment check
    # alone would leave an unconfigured deployment open. Both must say so.
    dev_organization_id: UUID | None = None

    @field_validator("dev_organization_id", mode="before")
    @classmethod
    def _empty_means_not_configured(cls, value: object) -> object:
        # Docker Compose passes an unset variable as an empty string.
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _development_tenant_only_in_development(self) -> Self:
        if self.dev_organization_id is not None and (
            self.environment not in DEVELOPMENT_ENVIRONMENTS
        ):
            raise ValueError(
                "dev_organization_id must not be set outside the local and test environments"
            )
        return self

    @field_validator("database_url")
    @classmethod
    def _database_url_scheme(cls, value: SecretStr) -> SecretStr:
        return _require_psycopg_url(value, "database_url")

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_origin(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("cors_origins must list explicit origins, not '*'")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def _explicit_hosts(cls, value: list[str]) -> list[str]:
        if any("*" in host or not host.strip() for host in value):
            raise ValueError("allowed_hosts must list explicit host names")
        return value


class MigrationSettings(LoggingSettings):
    """Configuration of the migration runner only. The API never loads this."""

    # Credentials of the *owner* role (gridwise_owner), which owns schemas and tables.
    migration_database_url: SecretStr

    @field_validator("migration_database_url")
    @classmethod
    def _migration_url_scheme(cls, value: SecretStr) -> SecretStr:
        return _require_psycopg_url(value, "migration_database_url")


class SeedSettings(MigrationSettings):
    """Configuration of the demonstration-data command only (gridwise_api.seed).

    It connects as the owner role, like the migration runner. ``environment`` has no
    default here: the command must be told where it is, and refuses anything but local and
    test.
    """

    environment: Environment


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_migration_settings() -> MigrationSettings:
    return MigrationSettings()
