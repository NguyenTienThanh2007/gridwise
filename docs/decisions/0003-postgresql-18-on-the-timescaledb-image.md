# 0003 — PostgreSQL 18 on the TimescaleDB image from P0

- Status: accepted (P0, 2026-11-11); telemetry section added after the P0 review

## Context

P0 needs PostgreSQL; P2 needs TimescaleDB for telemetry. Swapping the server image between
phases would mean a dump and restore, and two database servers would not fit in the
development machine's memory.

## Decision

Run one server, `timescale/timescaledb:2.31.0-pg18`, from P0.

- PostgreSQL 18 provides `uuidv7()` natively, so time-ordered primary keys need no
  extension and no application-side generation.
- The image **pre-installs the `timescaledb` extension in every new database** (observed,
  not assumed: the first schema drift test failed on Timescale's internal schemas). GRIDWISE
  creates no hypertables until P2.
- Alembic autogenerate and the schema drift test only look at schemas listed in
  `MANAGED_SCHEMAS` (`apps/api/src/gridwise_api/models/base.py`). Add each new schema there.
- PostgreSQL 18 images store data under `/var/lib/postgresql/<major>/docker`; the volume is
  mounted at `/var/lib/postgresql`.
- The tuner is capped (`TS_TUNE_MEMORY=1GB`, two CPUs) for the small development VM.

### Telemetry is off

By default the extension reports usage data to Timescale (`timescaledb.telemetry_level =
basic`; observed on the first P0 stack). GRIDWISE sets `TIMESCALEDB_TELEMETRY=off` in
`docker-compose.yml`, which CI also uses. An integration test
(`test_timescaledb_telemetry_is_disabled`) asserts the running server reports `off`.

The setting is written when the data directory is first initialised. A volume created
before this change keeps reporting until it is recreated (`make reset-db`) or the setting is
changed by hand (`ALTER SYSTEM SET timescaledb.telemetry_level = 'off'`).

### Health check uses TCP

During first-time initialisation the image runs a temporary server that listens on the Unix
socket only. A socket-based `pg_isready` therefore reports ready before any client can
connect (a 0.3–0.7 s window was measured locally). The health check is
`pg_isready -h 127.0.0.1`, so dependants start only once TCP connections are accepted.

## Consequences

- No image change at P2; enabling hypertables is an ordinary migration.
- Production must also run PostgreSQL 18 with TimescaleDB, or the `uuidv7()` defaults and
  later hypertables will not apply. Any production server needs telemetry switched off too.
- The image runs under the Timescale licence (`timescaledb.license = timescale`), not
  Apache 2.0. Its terms must be checked against the commercial hosting model before launch.
- Not verified: Airflow 3.4 against PostgreSQL 18. If it is unsupported, Airflow's metadata
  database gets its own server in P3.
