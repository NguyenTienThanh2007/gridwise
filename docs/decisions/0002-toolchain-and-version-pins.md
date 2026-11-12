# 0002 — Toolchain and version pins

- Status: accepted (P0, 2026-11-11)

## Decision

Versions were read from PyPI, npm and Docker Hub on 2026-11-11.

| Tool                 | Pin                   | Why                                                                                  |
| -------------------- | --------------------- | ------------------------------------------------------------------------------------ |
| Python               | 3.13                  | Supported by every planned dependency (pandapower, Airflow, LightGBM, scikit-learn). |
| FastAPI / Pydantic   | 0.162 / 2.14          | Current, mutually compatible.                                                        |
| SQLAlchemy / Alembic | 2.1.8+ / 1.20         | Current. Airflow excludes SQLAlchemy 2.1.0 only.                                     |
| psycopg              | 3.3                   | One driver for both the async API and synchronous migrations.                        |
| Node                 | 24                    | LTS release line.                                                                    |
| pnpm                 | 11.25.0               | Via `packageManager`.                                                                |
| Next.js / React      | 16.4.6 / 19.3.1       | Current. React Three Fiber 9 (P5) requires React `>=19 <19.4`.                       |
| Tailwind CSS         | 4.3.5                 | Current.                                                                             |
| **TypeScript**       | **6.0.3** (not 7.0)   | 7.0 is the new native compiler; lint and framework tooling support is unverified.    |
| **ESLint**           | **9.39.5** (not 10)   | typescript-eslint and the Next.js plugin are verified on 9. npm marks 9 deprecated.  |
| Prettier             | 3.9.9                 | 3.10.0 was newer than pnpm's minimum release age on the day of pinning.              |
| PostgreSQL           | 18 (TimescaleDB 2.31) | See 0003.                                                                            |

Python dependencies are declared as bounded ranges and fixed by `uv.lock`. Node dependencies
are declared as exact versions and fixed by `pnpm-lock.yaml`.

## Overrides

- `minimatch` is forced to 11.0.3 for GHSA-g3hv-75wg-m249. It arrives through
  typescript-eslint (development tooling only). Remove the override in
  `pnpm-workspace.yaml` once typescript-eslint depends on a patched release.

## Runtime upgrades are decisions, not bot updates

Dependabot ignores new Python releases for the container base image (3.14 and later, which
it classes as minor or major bumps), new Node majors for the base image, and `@types/node`
majors. Moving off Python 3.13 or Node 24 means updating `requires-python`,
`.python-version`, the images, CI and this record together. The first Dependabot run
proposed Python 3.15, Node 25 and Node 26 images; the Python one failed CI because the
project requires 3.13.

## Upgrade policy

- Dependabot opens weekly grouped minor and patch updates. TypeScript and ESLint majors are
  ignored there and upgraded deliberately, with this record updated.
- Major upgrades are reviewed one at a time and never batch-merged.
- CI fails on any known Python vulnerability and on moderate-or-higher Node advisories.

## Known holds for later phases

- `three` 0.187 is incompatible with `n8ao` at the time of writing. If P5 uses that library,
  hold `three` and `@types/three` below 0.187 until it is fixed.
