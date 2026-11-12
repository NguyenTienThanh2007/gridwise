# Architecture overview

GRIDWISE is a multi-tenant platform for monitoring, analysing, simulating and optimising
electrical distribution networks. It is a **simulation, monitoring and decision-support**
product: it has no path to real switching or control (see
[safety boundary](../security/safety-boundary.md)).

This document separates what exists today from what is planned. Planned parts are designs,
not commitments to a specific implementation; each is confirmed by a decision record when its
phase starts.

## What exists (P0 and P1.1)

```
browser ──HTTP──▶ web (Next.js 16)
   │
   └──HTTP (CORS, explicit origins)──▶ api (FastAPI) ──▶ PostgreSQL 18 (TimescaleDB image)
                                          ▲
                              migrate (Alembic, one-shot)
```

| Part        | Location                    | Responsibility                                          |
| ----------- | --------------------------- | ------------------------------------------------------- |
| API         | `apps/api/src/gridwise_api` | HTTP boundary, configuration, logging, health           |
| Migrations  | `apps/api/migrations`       | Schema history for the schemas GRIDWISE owns            |
| Web         | `apps/web`                  | App shell, ten routes, live platform status             |
| Local stack | `docker-compose.yml`        | postgres → migrate → api (default); web (profile `web`) |
| CI          | `.github/workflows/ci.yml`  | API, web, end-to-end and dependency-audit jobs          |

### Grid engine (P1.1, P1.2a)

`packages/grid-engine` is a library, not a service. Nothing calls it at runtime yet: the
API, database and web app are unchanged by P1.1 and P1.2a.

```
GridModel ─▶ validate ─▶ energisation ─▶ PowerFlowSolver ─▶ consistency checks ─▶ PowerFlowResult
                                              ▲
                                  adapters/pandapower_adapter
```

- Plain Python domain model (Bus, Line, Transformer, Load, Generator, ExternalGrid, Switch)
  with units in field names.
- Switches are states of the simulated network. Nothing sends them to equipment.
- Only the adapter imports pandapower; the API package may never import the adapter.
- A non-converged solve returns no values; de-energised elements are `None`, never zero.

Details: [grid-engine.md](../domain/grid-engine.md) and
[decision 0007](../decisions/0007-p1-grid-engine-architecture.md).

### API layering

```
api/routes/*      HTTP only: parse, call a service, shape the response
services/*        Business rules; no HTTP, no SQL
repositories/*    Data access; no business rules
models/*          SQLAlchemy tables
config.py         The only code that reads the environment
```

Route handlers never contain business logic. Services depend on repository _protocols_, so
unit tests substitute fakes and need no database.

### Health

- `GET /health/live`: the process is running. Touches no dependency.
- `GET /health/ready`: 200 only when the database is reachable **and** its schema is exactly
  the revision this build expects. Otherwise 503 with the reason:

| `database`        | Meaning                                                              |
| ----------------- | -------------------------------------------------------------------- |
| `ok`              | Reachable and at the expected revision                               |
| `unavailable`     | Cannot connect, timed out, or the query failed                       |
| `not_migrated`    | Reachable, but no migration has been applied                         |
| `schema_mismatch` | Reachable, but the applied revision is behind or ahead of this build |

The expected revision is `EXPECTED_SCHEMA_REVISION` (`schema_version.py`); a unit test fails
if it is not the Alembic head. The response carries both revisions.

### Errors

Every error response has one shape, and never contains a stack trace, an exception message
or the rejected input:

```json
{ "error": { "code": "internal_error", "message": "Internal server error", "request_id": "…" } }
```

An unhandled exception produces exactly one structured `unhandled_exception` log event with
the traceback, and a 500 that still carries CORS headers and `X-Request-ID`.

### Logging

One structured event per line. In containers every line is JSON, including uvicorn's and
Alembic's own messages, which are routed through the same formatter. Every request gets an
`X-Request-ID` (a well-formed caller value is kept, anything else is replaced) which is
bound to every log line of that request and returned in the response.

### Database roles

The API connects as `gridwise_app` and migrations as `gridwise_owner`; neither is a
superuser. See [decision 0006](../decisions/0006-separate-owner-and-runtime-database-roles.md).

## Planned (P1 onwards)

```
telemetry simulator ─▶ Redpanda ─▶ ingestion (bronze → silver) ─▶ PostgreSQL/TimescaleDB
                                        └─▶ object store (Parquet) ─▶ dbt (gold) ◀─ Airflow
grid-engine (pure Python + pandapower; no HTTP, no database) ◀─ imported by the API
forecasting (reads gold; writes model metadata, evaluations and forecasts)
```

| Phase | Adds                                                                                | Compose profile     |
| ----- | ----------------------------------------------------------------------------------- | ------------------- |
| P1    | Grid engine (P1.1 exists), `grid` and `sim` schemas, deterministic scenarios        | default             |
| P2    | `packages/shared` contracts, telemetry simulator, Redpanda, ingestion, object store | `streaming`, `lake` |
| P3    | dbt transformations, Airflow orchestration, gold KPIs                               | `orchestration`     |
| P4    | `packages/forecasting`: baselines, backtests, anomaly and overload risk             | none                |
| P5    | 3D digital twin bound to backend entities, playback                                 | none                |
| P6    | Authentication, RBAC, row-level security, audit, observability, deployment          | `observability`     |

Profiles exist because the development machine cannot hold every service in memory at once
(see [decision 0005](../decisions/0005-deviations-from-the-master-brief.md)).

### Database design by schema

| Schema   | Tables                                                                                                         | Phase   |
| -------- | -------------------------------------------------------------------------------------------------------------- | ------- |
| `core`   | `organizations` (exists), users, memberships, audit_log                                                        | P0 / P6 |
| `grid`   | grids, substations, buses, transformers, lines, switches, feeders, generators, loads, storage, meters, sensors | P1      |
| `sim`    | scenarios, simulation_runs (seed, engine version, input hash), results                                         | P1      |
| `bronze` | raw_events (event ID, original payload, source, schema version, ingestion time)                                | P2      |
| `silver` | measurements hypertable (nullable value, unit, quality flag)                                                   | P2      |
| `gold`   | dbt-built KPI and feature tables                                                                               | P3      |
| `ml`     | models, versions, evaluations, forecasts                                                                       | P4      |
| `ops`    | grid_events, alerts                                                                                            | P2–P5   |

Rules that apply to every future table:

- Tenant-owned tables carry `organization_id`, and child tables use composite foreign keys
  that include it ([decision 0004](../decisions/0004-tenant-column-from-the-first-migration.md)).
- Keys are UUIDv7 (`uuidv7()` is built into PostgreSQL 18).
- Every grid and measurement carries a non-null provenance (`synthetic`, `public_dataset`,
  `customer`). Synthetic data is never presented as measured.
- Missing telemetry is stored as NULL with a quality flag, never as zero.
- Simulated (business) time and wall-clock (ingestion, publication) time are separate columns.
