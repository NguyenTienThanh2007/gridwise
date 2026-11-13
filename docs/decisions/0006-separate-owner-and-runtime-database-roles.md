# 0006 — Separate owner and runtime database roles

- Status: accepted (P0 remediation, 2026-11-11)

## Context

The first P0 stack connected the API and the migrations as the image's bootstrap user: a
superuser with `BYPASSRLS` that also owned every table. PostgreSQL does not apply row-level
security to superusers, to roles with `BYPASSRLS`, or (by default) to a table's owner. The
tenant isolation planned in 0004 would have been silently ineffective.

## Decision

Three roles, each with one job:

| Role             | Used by                                                                              | Attributes                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `postgres`       | Nothing at runtime. Integration tests use it to create and drop throwaway databases. | Superuser (image bootstrap role)                                                                              |
| `gridwise_owner` | Alembic (`migrate` service, `make migrate`)                                          | Login. No superuser, `BYPASSRLS`, `CREATEDB`, `CREATEROLE`. Owns the database, schemas, tables and functions. |
| `gridwise_app`   | The API                                                                              | Login, `NOINHERIT`. No superuser, `BYPASSRLS`, `CREATEDB`, `CREATEROLE`. Owns nothing. Member of no role.     |

- The roles are created by `infrastructure/postgres/init/010-gridwise-roles.sh` when the
  data directory is first initialised. Passwords are read from the environment by `psql`
  (`\getenv`), not passed on a command line.
- `CONNECT` on the database is revoked from `PUBLIC` and granted to `gridwise_app`.
- Privileges for `gridwise_app` are granted **explicitly, per object, in the migration that
  creates the object**. There are no default privileges, so a new table is invisible to the
  API until a migration says otherwise.
- Two settings, two URLs: the API reads `GRIDWISE_DATABASE_URL` (`Settings`); Alembic reads
  `GRIDWISE_MIGRATION_DATABASE_URL` (`MigrationSettings`). Neither class can see the other's
  URL, and in Docker Compose each service receives only its own.
- Migrations refuse to run as a superuser (`migrations/env.py`), because objects created by
  a superuser would be owned by it.

Current grants to `gridwise_app` (asserted exactly by `test_roles.py`):

| Object                           | Privilege                              | Why                                   |
| -------------------------------- | -------------------------------------- | ------------------------------------- |
| schema `core`                    | `USAGE`                                | Reach objects in it                   |
| `core.organizations`             | `SELECT`                               | Read its own tenant row (policy 0004) |
| `core.current_organization_id()` | `EXECUTE`                              | Used by row-level security policies   |
| `public.alembic_version`         | `SELECT`                               | Readiness compares schema revisions   |
| schema `grid`                    | `USAGE`                                | Reach objects in it (P1.2b)           |
| the eight `grid` tables          | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | Grid data, filtered by policy (0008)  |

## Conventions for every later migration

1. Create objects as the owner role (never edit the role in a migration).
2. Grant `gridwise_app` only the privileges the API needs on the new object, by name.
3. If the table has `updated_at`, attach the `core.set_updated_at()` trigger.
4. If the table is tenant-owned, enable row-level security and add a policy `TO gridwise_app`
   using `core.current_organization_id()`.
5. Extend the expected grant list in `test_roles.py`.

## Consequences

- An existing local volume has no such roles. `make reset-db` then `make up` recreates it;
  the baseline migration fails with that instruction if the runtime role is missing.
- Role creation lives in an init script, not in a migration, because roles are cluster-wide
  and need passwords. A production deployment must create the same two roles by its own
  means (infrastructure code or a managed-database console) before the first migration.
- Changing a role password means `ALTER ROLE` on the server; editing `.env` alone does not
  change an initialised database.
- Passwords are placed into connection URLs without encoding. They must not contain URL
  delimiters (`@ : / ? #`); `.env.example` says so. A structured (non-URL) setting is the
  proper fix and is deferred.
- The integration tests need the superuser URL (`GRIDWISE_TEST_ADMIN_DATABASE_URL`). It is
  read only by the test suite and is never given to the API or to Alembic.
