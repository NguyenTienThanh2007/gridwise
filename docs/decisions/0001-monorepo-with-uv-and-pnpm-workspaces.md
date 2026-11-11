# 0001 — Monorepo with uv and pnpm workspaces

- Status: accepted (P0, 2026-11-11)

## Context

The brief asks for a modular monorepo with separate frontend, API, grid engine, data
platform and forecasting, reproducible local development and pinned dependencies.

## Decision

- **Python:** one uv workspace rooted at the repository, one committed `uv.lock`. Members
  are added when they contain code; P0 has `apps/api` only.
- **Node:** one pnpm workspace, one committed `pnpm-lock.yaml`. P0 has `apps/web` only.
- **Airflow and dbt** (P3) get their own isolated environments and images. They are never
  members of the application lockfile, because their dependency constraints (their own
  FastAPI, SQLAlchemy, protobuf ranges) must not dictate the API's.
- Tool configuration (ruff, mypy, pytest, ESLint, Prettier) lives at the root so every
  package is held to the same rules.
- `make` is the single entry point; each target is a thin wrapper over `uv`, `pnpm` or
  `docker compose`.

## Consequences

- One resolution per language: packages cannot drift onto incompatible versions.
- pandapower currently requires `pandas~=2.3` and `numpy<2.5`. When `grid-engine` joins the
  workspace in P1, the whole Python workspace stays on pandas 2.3 until pandapower moves.
- Directories from the brief's structure appear only when a phase puts code in them.
