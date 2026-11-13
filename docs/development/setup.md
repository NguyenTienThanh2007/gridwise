# Development setup

## Prerequisites

| Tool   | Version              | Notes                                  |
| ------ | -------------------- | -------------------------------------- |
| uv     | 0.12 or newer        | Installs Python 3.13 itself if missing |
| Node   | 24                   |                                        |
| pnpm   | 11.25 (corepack)     | `corepack enable`                      |
| Docker | Compose 5.2 (tested) |                                        |
| make   | any                  |                                        |

## First run

```bash
make setup      # creates .env, installs Python and Node dependencies
make up         # postgres + migrations + API, waits until healthy
make dev-web    # web app with hot reload
```

Then open <http://localhost:3100>. The dashboard should show **Ready**.

To run the web app in a container instead of on the host: `make up-web`.

## Ports

All host ports come from `.env` and are bound to `127.0.0.1`.

| Variable        | Default | Service    |
| --------------- | ------- | ---------- |
| `POSTGRES_PORT` | 5450    | PostgreSQL |
| `API_PORT`      | 8020    | API        |
| `WEB_PORT`      | 3100    | Web        |

If you change a port, also update the three database URLs,
`GRIDWISE_CORS_ORIGINS` and `NEXT_PUBLIC_API_URL` in `.env` to match. The defaults avoid
3000, 8000 and 5432 on purpose, because other projects commonly hold them.

## Commands

| Command                 | What it does                                                             | Needs     |
| ----------------------- | ------------------------------------------------------------------------ | --------- |
| `make lint`             | ruff format check, ruff, Prettier check, ESLint                          | nothing   |
| `make typecheck`        | mypy (strict), tsc                                                       | nothing   |
| `make test`             | Python and web unit tests                                                | nothing   |
| `make test-engine`      | Grid engine tests and its closed-form self-check                         | nothing   |
| `make test-integration` | Migration, role, isolation, repository and seed tests on real PostgreSQL | `make up` |
| `make migrate`          | Apply migrations as the owner role                                       | `make up` |
| `make seed-demo`        | Create the synthetic demo organisation and grid (local and test only)    | migrated  |
| `make test-e2e`         | Builds the web app, runs Playwright against it and the API               | `make up` |
| `make check`            | lint, typecheck, test, test-integration, web build, bundle secret check  | `make up` |
| `make audit`            | pip-audit and pnpm audit                                                 | network   |
| `make fmt`              | Apply formatting                                                         | nothing   |
| `make down`             | Stop the stack, keep data                                                |           |
| `make reset-db`         | Stop the stack and delete the database volume                            |           |

Integration tests create a throwaway database per test on the configured server and drop it
afterwards. They never migrate or modify your development database.

The first end-to-end run needs a browser: `pnpm --filter @gridwise/web exec playwright install chromium`.

## Database roles and credentials

| Role             | `.env` variable                    | Used by                  |
| ---------------- | ---------------------------------- | ------------------------ |
| `gridwise_app`   | `GRIDWISE_DATABASE_URL`            | The API                  |
| `gridwise_owner` | `GRIDWISE_MIGRATION_DATABASE_URL`  | Alembic (`make migrate`) |
| `postgres`       | `GRIDWISE_TEST_ADMIN_DATABASE_URL` | Integration tests only   |

The roles are created when the database volume is first initialised. If you have a volume
from before the roles existed, or you change a password in `.env`, run `make reset-db`
(this deletes local data) and then `make up`.

## Database changes

1. Change or add a model under `apps/api/src/gridwise_api/models` and import it in
   `models/__init__.py`.
2. If it lives in a new schema, add the schema to `MANAGED_SCHEMAS` in `models/base.py`.
3. From `apps/api`:
   `uv run alembic revision --autogenerate --rev-id 0002 -m "describe the change"`
   (revision IDs are sequential four-digit numbers).
4. Review the generated file by hand and write a real `downgrade`. Then add what
   autogenerate cannot see (decision 0006):
   - `GRANT` to `gridwise_app` only the privileges the API needs on the new objects;
   - the `core.set_updated_at()` trigger, if the table has `updated_at`;
   - `ENABLE ROW LEVEL SECURITY` and a policy, if the table is tenant-owned;
   - row checks (`CHECK` constraints). The models describe columns, keys and indexes only,
     so autogenerate never adds, changes or removes a check: write each one in the
     migration and test it (`tests/integration/test_grid_constraints.py` shows how);
   - for a tenant-owned table, put `organization_id` first in every unique constraint,
     so a duplicate-key error can never reveal another tenant's rows (decision 0008).
5. Set `EXPECTED_SCHEMA_REVISION` in `schema_version.py` to the new revision. Until you do,
   a unit test fails and the API reports `schema_mismatch`.
6. Extend the expected grant list in `tests/integration/test_roles.py`.
7. `make test-integration`: the round-trip, drift, role and isolation tests must pass.

Never edit a migration that has been merged. Add a new one.

## Demonstration data

`make seed-demo` creates one organisation ("Development organisation (synthetic)") and one
grid, the CIGRE medium-voltage benchmark. It is a published test network: synthetic, not a
real grid, and it contains no measurements.

- It runs as the owner role and refuses any environment other than `local` and `test`.
- Running it again changes nothing. If you changed the demonstration grid, it stops and
  asks for `--replace`:
  `PYTHONPATH=apps/api/src:packages/grid-engine/src uv run python -m gridwise_api.seed --replace`
- `GRIDWISE_DEV_ORGANIZATION_ID` in `.env` names the seeded organisation. The API accepts
  that setting only in `local` and `test`. It selects a tenant; it is not a credential and
  protects nothing ([decision 0008](../decisions/0008-grid-persistence-and-development-tenant.md)).

A database created before P1.2b is at revision `0001`: run `make migrate` first. Until then
the API's readiness check reports `schema_mismatch`.

## Gotchas

- `NEXT_PUBLIC_API_URL` is compiled into the browser bundle. Rebuild the web app after
  changing it.
- The end-to-end tests use `http://localhost:…`, not `127.0.0.1`: the API's CORS allow-list
  matches origins exactly.
- The TimescaleDB image installs its extension in every new database. This is expected
  (decision 0003).
- On macOS the virtualenv's editable-install `.pth` file can get the hidden flag, which
  Python 3.13 ignores. pytest, mypy, Alembic and `make dev-api` all set the source path
  explicitly, so use those entry points rather than a bare `python -c "import gridwise_api"`.
- `make` does not load `.env` into your shell or into recipes (it holds database
  credentials). To override a port for one command: `make dev-api API_PORT=8030`.
- pnpm rejects packages published in the last day (minimum release age). If an install adds
  a `minimumReleaseAgeExclude` entry to `pnpm-workspace.yaml`, pin an older version instead
  of committing the exclusion.
