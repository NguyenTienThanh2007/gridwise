from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep migrations reviewable and reversible.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Schemas owned by GRIDWISE migrations. Everything else in the database (for example the
# internal schemas the TimescaleDB image pre-installs) is invisible to autogenerate.
MANAGED_SCHEMAS = frozenset({"core"})


def include_managed_names(name: str | None, type_: str, parent_names: object) -> bool:
    """Alembic ``include_name`` hook: reflect only the schemas we manage."""
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
