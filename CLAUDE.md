# CLAUDE.md — GRIDWISE

Smart grid digital twin: simulation, monitoring and decision support for electrical
distribution networks. Phases and acceptance criteria are in `docs/ROADMAP.md`.

## Current state

- **P0 (foundation) is merged** (PR 1). All four CI jobs passed on the PR and on `main`.
- **P1.1 (grid engine scaffold) is merged** (PR 7): model, validation, pandapower adapter,
  power flow for Bus / Line / Load / ExternalGrid.
- **P1.2a (engine: Transformer, Generator, Switch, CIGRE MV benchmark) is merged** (PR 8).
- **P1.2b (database: `grid` schema, row-level security, `tenancy.tenant_transaction`,
  `make seed-demo`) is merged** (PR 9). Design: decision 0008.
- **P1.2c (grid API under `/api/v1/grids`, ETag/If-Match, engine validation per write):**
  implementation complete; pending review, CI verification and merge. Design: decision 0009.
- **Next:** P1.3 simulation, once approved. Do not start a milestone without owner approval.

## Hard boundaries

- No real-world control: no switching commands, no SCADA/OT writes, no outbound integration
  to control systems (`docs/security/safety-boundary.md`).
- Never present synthetic data as measured. Every grid and measurement carries provenance.
- Never convert missing telemetry to zero.
- Do not invent electrical formulas or parameters; use pandapower and cited sources.
- A failed or non-converged power flow returns no values. De-energised elements are `None`,
  never zero. Never weaken the engine's consistency checks to make a result pass.
- Tenant data is reached only through `tenancy.tenant_transaction`. Never set tenant
  context with a session-level `SET`, never from a request value, never weaken a policy.
- A new API route must be added to the allow-list in `tests/unit/test_system.py`. Platform
  endpoints stay read-only; grid writes change stored simulation data only.
- The development tenant, the grid API and `make seed-demo` exist in `local` and `test` only. Migrations
  run as `gridwise_owner`, never as `gridwise_app` and never as a superuser.

## Architecture (one screen)

- `apps/api`: FastAPI. `api/routes` (HTTP only) → `services` (rules) → `repositories` (SQL).
  `config.py` is the only code that reads the environment.
- `apps/api/migrations`: Alembic, run as `gridwise_owner`. The only way GRIDWISE-owned
  schemas change. Every migration grants `gridwise_app` its privileges explicitly, and the
  same change bumps `EXPECTED_SCHEMA_REVISION` (decision 0006, `docs/development/setup.md`).
- Database roles: API = `gridwise_app` (no superuser, no BYPASSRLS, owns nothing);
  migrations = `gridwise_owner`; `postgres` superuser only for integration tests.
- `packages/grid-engine`: pure domain engine (dataclasses, no Pydantic, no HTTP, no SQL).
  ONLY `adapters/pandapower_adapter.py` may import pandapower, pandas, numpy or scipy;
  `apps/api` must never import the adapter. Both are enforced by tests. Entry point:
  `run_power_flow(grid, solver)`. Model, equations, error codes and limits:
  `docs/domain/grid-engine.md`.
- `apps/web`: Next.js 16 app shell. Placeholder routes show no data until the backend has it.
- One PostgreSQL 18 server on the TimescaleDB image. Schemas by domain; add each new schema
  to `MANAGED_SCHEMAS` in `models/base.py`.
- Tenant-owned tables carry `organization_id` and a row-level security policy from their
  first migration (decision 0004). Tenant isolation is NOT complete: nothing sets tenant
  context yet. Never claim otherwise.
- Details: `docs/architecture/overview.md`, `docs/decisions/`.

## Commands

```bash
make setup                 # .env + uv sync + pnpm install
make up                    # postgres + migrate + api (waits for health)
make check                 # lint, typecheck, unit + integration tests, web build (needs `make up`)
make test-e2e              # Playwright (needs `make up`)
make test-engine           # grid engine tests + closed-form self-check
make audit                 # pip-audit + pnpm audit
```

## Conventions

- Conventional Commits; phase branches; never merge to `main` without owner approval.
- Report checks as PASS / FAIL / BLOCKED / NOT RUN. Never claim unexecuted results.
- Never weaken or delete a test to make it pass.
- Create directories and packages only when real code needs them (decision 0005).
- Record architectural decisions and any deviation from the brief in `docs/decisions/`.
- Never edit a merged migration; add a new one with a working `downgrade`.

## Gotchas

- Host ports are 5450 / 8020 / 3100 (`.env`); 3000, 8000 and 5432 are often taken.
- Docker has about 4 GB on the dev machine: keep new services behind Compose profiles.
- The TimescaleDB image pre-installs its extension in every database (decision 0003).
- TypeScript is pinned to 6.0 and ESLint to 9 (decision 0002).
- `NEXT_PUBLIC_API_URL` is baked in at build time; rebuild after changing it.
- pnpm's minimum release age rejects day-old packages: pin an older version, do not commit
  a `minimumReleaseAgeExclude` entry.
- `make` does not export `.env`; the web build must never see database credentials
  (`pnpm check:bundle` enforces it).
- Old local database volume without roles: `make reset-db && make up`.
- Engine error codes are a contract: never rename one; add new ones to the enum, the
  frozen-list test and the table in `docs/domain/grid-engine.md`.
- pandapower pins pandas ~2.3 and numpy <2.5 for the whole workspace; it prints a numba
  notice on import, which is expected (numba is not installed).
- MinIO is unavailable as specified in the brief; the object store is chosen in P2.
