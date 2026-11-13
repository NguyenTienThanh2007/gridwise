# GRIDWISE

A smart grid digital twin: a multi-tenant platform for monitoring, analysing, simulating and
optimising electrical distribution networks.

> **GRIDWISE is a simulation, monitoring and decision-support product.** It does not issue
> switching commands, operate substations or write to SCADA/OT systems. All data in this
> repository is synthetic or absent; nothing here is a real grid measurement.

## Status

**P0 (foundation) is merged.** All four CI jobs pass on `main`.

**P1.1 (grid engine scaffold) is merged**: a pure Python engine that solves the balanced AC
power flow of a network of buses, lines, loads and an external grid.

**P1.2a (transformers, generators and switches in the engine) is merged.** It also ships the
CIGRE medium-voltage benchmark as a synthetic demonstration network.

**P1.2b (grid database): implementation complete; pending review, CI verification and
merge.** It adds the `grid` schema with row-level security, a transaction-scoped tenant
context, and a command that seeds the synthetic demonstration grid.

No HTTP endpoint reads or writes grids yet, the engine is not called by the API, and the web
app is unchanged. There is no authentication: tenant isolation exists in the database, but
nothing yet decides who may act for which tenant. See [docs/ROADMAP.md](docs/ROADMAP.md).

What works today:

- FastAPI service with validated configuration, JSON logs, request IDs, one error format
  and liveness/readiness endpoints.
- PostgreSQL 18 with an Alembic baseline migration (`core.organizations`, the tenant table)
  and separate owner and runtime database roles.
- Next.js app shell with the ten product routes and a dashboard that shows live API and
  database status. The grid, simulation and analytics routes are labelled placeholders.
- Grid engine library (`packages/grid-engine`): electrical model with validation and stable
  error codes, AC Newton-Raphson power flow through pandapower, checked against closed-form
  solutions. Its limits are listed in [docs/domain/grid-engine.md](docs/domain/grid-engine.md).
- Docker Compose stack, Makefile, GitHub Actions CI, dependency audit and Dependabot.

There is no telemetry, analytics, forecasting or 3D twin yet.

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 24 with pnpm (`corepack enable`),
Docker, make.

```bash
make setup      # creates .env, installs dependencies
make up         # postgres + migrations + API
make dev-web    # web app on http://localhost:3100
```

The dashboard should report **Ready**. API docs: <http://localhost:8020/docs>.

Ports (5450, 8020, 3100) are set in `.env`. Full instructions:
[docs/development/setup.md](docs/development/setup.md).

## Checks

```bash
make check      # lint, type checks, unit and integration tests, web build
make test-e2e   # browser tests against the running stack
make audit      # dependency vulnerability scan
```

## Layout

```
apps/api/             FastAPI service, Alembic migrations, tests
apps/web/             Next.js app, unit tests, Playwright end-to-end tests
packages/grid-engine/ Electrical model, validation and power flow (no HTTP, no database)
infrastructure/docker Dockerfiles
docs/                 Architecture, decisions, development, security, roadmap
docker-compose.yml    Local stack
Makefile              All developer commands
```

Packages for the data platform and forecasting are added in the phase that implements them.

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Decision records](docs/decisions/)
- [Grid engine: model, equations and limits](docs/domain/grid-engine.md)
- [Safety boundary and data provenance](docs/security/safety-boundary.md)
- [Development setup](docs/development/setup.md)
- [Roadmap and acceptance criteria](docs/ROADMAP.md)

## Licence

No licence has been chosen yet. Until one is added, all rights are reserved.
