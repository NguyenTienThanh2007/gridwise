"""Baseline: core schema, the tenant table, and the database conventions.

Establishes three conventions every later migration follows:

1. Ownership and grants. Objects are owned by the migration role (the role running this
   file). The runtime role ``gridwise_app`` owns nothing and receives only the privileges
   named here, table by table. There are no default privileges.
2. ``updated_at`` is maintained by the ``core.set_updated_at()`` trigger.
3. Tenant-scoped rows are filtered by row-level security against
   ``core.current_organization_id()``, which reads the transaction-local setting
   ``app.current_organization_id``.

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUNTIME_ROLE = "gridwise_app"


def _require_runtime_role() -> None:
    exists = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": RUNTIME_ROLE})
        .scalar()
    )
    if not exists:
        raise RuntimeError(
            f"Role {RUNTIME_ROLE!r} does not exist. It is created on the first start of the "
            "database by infrastructure/postgres/init/010-gridwise-roles.sh. For a local "
            "volume created before that script existed, run `make reset-db` then `make up`."
        )


def upgrade() -> None:
    _require_runtime_role()

    op.execute("CREATE SCHEMA core")

    # --- Convention 2: updated_at -------------------------------------------------------
    op.execute(
        """
        CREATE FUNCTION core.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END
        $$
        """
    )

    # --- Convention 3: tenant context ---------------------------------------------------
    # NULLIF: once a custom setting has been set in a session, PostgreSQL reports it as ''
    # (not NULL) after the transaction ends. Both mean "no tenant": the policy matches
    # nothing. A malformed value fails the cast, which fails the query (closed, not open).
    op.execute(
        """
        CREATE FUNCTION core.current_organization_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.current_organization_id', true), '')::uuid
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION core.set_updated_at() FROM PUBLIC")
    op.execute("REVOKE ALL ON FUNCTION core.current_organization_id() FROM PUBLIC")

    op.create_table(
        "organizations",
        # uuidv7() is built into PostgreSQL 18: time-ordered keys without an extension.
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_organizations_slug_format"
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_organizations_name_not_blank"),
        schema="core",
    )
    op.execute(
        """
        CREATE TRIGGER set_updated_at BEFORE UPDATE ON core.organizations
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at()
        """
    )

    # A runtime session sees only the organisation named by its transaction's tenant
    # context, and nothing at all without one.
    op.execute("ALTER TABLE core.organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY organization_is_current_tenant ON core.organizations
        FOR SELECT TO {RUNTIME_ROLE}
        USING (id = core.current_organization_id())
        """
    )

    # --- Convention 1: explicit, minimal grants -----------------------------------------
    op.execute(f"GRANT USAGE ON SCHEMA core TO {RUNTIME_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION core.current_organization_id() TO {RUNTIME_ROLE}")
    op.execute(f"GRANT SELECT ON core.organizations TO {RUNTIME_ROLE}")
    # Readiness compares the applied revision with the one the API expects.
    op.execute(f"GRANT SELECT ON public.alembic_version TO {RUNTIME_ROLE}")


def downgrade() -> None:
    # public.alembic_version outlives a downgrade to base, and so does its SELECT grant.
    op.execute("DROP POLICY organization_is_current_tenant ON core.organizations")
    op.drop_table("organizations", schema="core")
    op.execute("DROP FUNCTION core.current_organization_id()")
    op.execute("DROP FUNCTION core.set_updated_at()")
    op.execute(f"REVOKE USAGE ON SCHEMA core FROM {RUNTIME_ROLE}")
    op.execute("DROP SCHEMA core")
