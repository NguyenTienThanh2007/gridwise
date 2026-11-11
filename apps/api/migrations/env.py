"""Alembic environment. Online mode only: migrations always run against a database.

Migrations connect as the owner role (GRIDWISE_MIGRATION_DATABASE_URL), never as the API's
runtime role and never as a superuser: objects created by a superuser would be owned by it.
"""

import logging

from alembic import context
from sqlalchemy import create_engine, text

from gridwise_api.config import get_migration_settings
from gridwise_api.logging import configure_logging
from gridwise_api.models import Base
from gridwise_api.models.base import include_managed_names

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    # Tests pass a throwaway database through attributes; everything else uses settings.
    override = config.attributes.get("database_url")
    if isinstance(override, str):
        return override
    return get_migration_settings().migration_database_url.get_secret_value()


def _configure_logging() -> None:
    if not config.attributes.get("configure_logging", True):
        return  # tests keep pytest's own log capture
    configure_logging(get_migration_settings())
    logging.getLogger("alembic").setLevel(logging.INFO)


def run_migrations() -> None:
    # hide_parameters: keep bound values out of error messages and logs.
    engine = create_engine(_database_url(), hide_parameters=True)
    try:
        with engine.connect() as connection:
            is_superuser = connection.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
            if is_superuser:
                raise RuntimeError(
                    "Refusing to run migrations as a PostgreSQL superuser. Use the owner "
                    "role (GRIDWISE_MIGRATION_DATABASE_URL), so that it owns what it creates."
                )
            connection.rollback()  # leave no open transaction for Alembic to trip over

            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_schemas=True,
                include_name=include_managed_names,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported; run against a database.")
_configure_logging()
run_migrations()
