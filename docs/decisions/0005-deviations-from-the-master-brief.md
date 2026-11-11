# 0005 — Deviations from the master brief

- Status: accepted for P0; items marked "open" are decided when their phase starts

The brief allows refinements when they are justified and documented. These are all of them.

| #   | Brief                                 | Deviation                                                 | Status   |
| --- | ------------------------------------- | --------------------------------------------------------- | -------- |
| 1   | Full directory tree created up front  | Directories are created when a phase adds code to them    | accepted |
| 2   | Top-level `tests/` for all tests      | Unit and integration tests sit with their package         | accepted |
| 3   | MinIO                                 | Not available as specified; replacement chosen in P2      | open     |
| 4   | Apache Kafka or Redpanda              | Redpanda intended (single binary, lower memory)           | open     |
| 5   | MQTT where appropriate                | Deferred until a device-gateway requirement exists        | open     |
| 6   | Multi-tenancy in P6                   | Tenant column from the first migration; enforcement in P6 | accepted |
| 7   | PostgreSQL in P0, TimescaleDB in P2   | TimescaleDB image from P0                                 | accepted |
| 8   | Prometheus, Grafana in infrastructure | Added in P6 behind a Compose profile                      | accepted |

## Notes

**1, 2 — Structure.** Empty directories describe intent, not the system, and go stale.
End-to-end tests live in `apps/web/e2e` because they are driven by the web toolchain.
Top-level `tests/` is reserved for suites that span services (P2 onwards).

**3 — MinIO.** On 2026-11-11 the `minio/minio` image was no longer on Docker Hub and the
GitHub repository was archived. Application code will depend on the S3 API only, so the
choice of server stays replaceable. Candidates are evaluated and recorded in P2.

**4, 5 — Messaging.** One broker is enough until a requirement says otherwise.

**8 — Memory.** The development machine has 8 GB of RAM with about 4 GB given to Docker,
shared with other projects. Measured P0 footprint: postgres 44 MiB, API 68 MiB, web 49 MiB.
Airflow, a broker, an object store and an observability stack will not fit alongside each
other, so every later service sits behind a profile and the default stack stays small.

**Schema ownership.** "Migrations are the only way the schema changes" holds for the schemas
GRIDWISE owns (`MANAGED_SCHEMAS`). From P3, dbt will own the `gold` schema and Airflow its
own metadata; Alembic will neither create nor compare those.
