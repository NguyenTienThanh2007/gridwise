# GRIDWISE

A smart grid digital twin: a multi-tenant platform for monitoring, analysing, simulating and
optimising electrical distribution networks.

> **GRIDWISE is a simulation, monitoring and decision-support product.** It does not issue
> switching commands, operate substations or write to SCADA/OT systems. All data in this
> repository is synthetic or absent; nothing here is a real grid measurement.

## Status

**P0 (foundation) is implemented.** There is no grid model, telemetry, analytics, forecasting
or 3D twin yet; those routes exist as labelled placeholders. See
[docs/ROADMAP.md](docs/ROADMAP.md).

What works today:

- FastAPI service with validated configuration, JSON logs, request IDs, one error format
  and liveness/readiness endpoints.
- PostgreSQL 18 with an Alembic baseline migration (`core.organizations`, the tenant table)
  and separate owner and runtime database roles.
- Next.js app shell with the ten product routes and a dashboard that shows live API and
  database status.
- Docker Compose stack, Makefile and dependency audit.
- A CI workflow and Dependabot configuration are written but **have not run yet**: the
  branch has not been pushed.

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
infrastructure/docker Dockerfiles
docs/                 Architecture, decisions, development, security, roadmap
docker-compose.yml    Local stack
Makefile              All developer commands
```

Packages for the grid engine, data platform and forecasting are added in the phase that
implements them.

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Decision records](docs/decisions/)
- [Safety boundary and data provenance](docs/security/safety-boundary.md)
- [Development setup](docs/development/setup.md)
- [Roadmap and acceptance criteria](docs/ROADMAP.md)

## Licence

No licence has been chosen yet. Until one is added, all rights are reserved.
