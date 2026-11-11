# Roadmap

A phase starts only after the previous one is verified. Results are reported as
PASS / FAIL / BLOCKED / NOT RUN, and never claimed without being executed.

## P0 — Foundation (implemented and remediated after review; CI not yet run)

| #   | Acceptance criterion                                                            | Evidence                                          |
| --- | ------------------------------------------------------------------------------- | ------------------------------------------------- |
| 1   | `make setup` works from a fresh clone using only `.env.example`                 | `make setup`                                      |
| 2   | `docker compose up -d --wait` reports every default service healthy             | `make up`, `docker compose ps`                    |
| 3   | `/health/ready` is 200 with the database up and 503 with it down                | unit + integration tests; manual stop of postgres |
| 4   | Migrations upgrade from empty, downgrade to base and upgrade again              | `test_upgrade_downgrade_upgrade_round_trip`       |
| 5   | Models and migrations cannot drift apart                                        | `test_models_match_the_migrated_schema`           |
| 6   | Format, lint, type checks, tests and web build pass locally                     | `make check`                                      |
| 7   | The same checks pass in CI on a pull request                                    | `.github/workflows/ci.yml`                        |
| 8   | An end-to-end test loads the web shell and shows live API status                | `make test-e2e`                                   |
| 9   | No secrets committed; configuration loads through one validated settings module | `config.py`, `test_config.py`, `.gitignore`       |
| 10  | A new developer can follow the README to a running stack                        | `README.md`, `docs/development/setup.md`          |

Status of each criterion is recorded in the P0 pull request, not here.

## P1 — Grid domain engine

Domain entities, network topology, pandapower integration, power-flow calculations and the
six deterministic scenarios (normal operation, rising industrial demand, transformer
overload, feeder outage, renewable increase, battery charge and discharge).

Draft acceptance criteria (confirmed at phase start):

- `packages/grid-engine` has no HTTP, database or frontend imports (enforced by a test).
- Network parameters come from pandapower standard types or a cited public benchmark network.
- Power-flow results match pandapower's own results for a published reference network.
- Same network, scenario and seed give identical results, verified by a stored fixture.
- Topology and parameter validation rejects islands, missing slack and out-of-range values
  with specific errors; non-convergence is reported, never hidden.
- Model assumptions and limitations are documented in `docs/domain/`.

## P2 — Data platform

Synthetic telemetry, broker, TimescaleDB hypertables, object storage, validation, streaming
APIs. Idempotent ingestion, duplicate and late-event handling, explicit quality flags.

## P3 — Analytics platform

dbt, Airflow, bronze/silver/gold, energy KPIs, data-quality checks, lineage, backfills.

## P4 — Intelligence

Load forecasting from transparent baselines, anomaly detection, transformer overload risk.
Time-based backtests with MAE, RMSE and WAPE; leakage checks; stored model metadata.

## P5 — Digital twin

Interactive 3D network bound to backend entities, live status, historical playback,
simulation controls.

## P6 — Startup readiness

Authentication, RBAC, row-level security, audit log, rate limiting, observability, cloud
deployment, pilot workflows.
