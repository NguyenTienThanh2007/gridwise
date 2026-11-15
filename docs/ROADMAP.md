# Roadmap

A phase starts only after the previous one is verified. Results are reported as
PASS / FAIL / BLOCKED / NOT RUN, and never claimed without being executed.

## P0 — Foundation (merged; CI green on `main`)

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

All ten criteria passed. Criterion 7 was met on pull request 1 (head `7773bdd`) and again on
`main` (`f4785cd`): API, Web, End to end and Dependency audit all succeeded.

## P1 — Grid engine

Architecture: [decision 0007](decisions/0007-p1-grid-engine-architecture.md). Model and
limits: [docs/domain/grid-engine.md](domain/grid-engine.md).

### P1.1 — Engine scaffold (merged, pull request 7)

Bus, Line, Load and ExternalGrid; validation with stable error codes; AC Newton-Raphson
power flow through a pandapower adapter; typed results; input and result hashes.

| #   | Acceptance criterion                                                                     | Evidence                            |
| --- | ---------------------------------------------------------------------------------------- | ----------------------------------- |
| 1   | A two-bus network matches an independently derived closed-form solution                  | `test_two_bus_analytic.py`          |
| 2   | Identical inputs give identical normalised result hashes                                 | `test_determinism.py`               |
| 3   | Only the adapter imports pandapower; the engine imports no web or database library       | `test_import_boundary.py`           |
| 4   | Missing slack, zero-length lines and invalid voltages are rejected with documented codes | `test_validation.py`                |
| 5   | A non-converged power flow returns no values, including right after a successful one     | `test_non_convergence.py`           |
| 6   | De-energised elements have no values and lost load is reported                           | `test_topology.py`                  |
| 7   | Engine tests run on Linux in CI and the API image builds with the solver stack           | CI job "Grid engine"                |
| 8   | All P0 checks still pass                                                                 | CI jobs API, Web, End to end, Audit |

All eight criteria passed on pull request 7 and on `main` (`930c5b7`), including the hash
regression on Linux x86-64.

### P1.2 — Persistence and grid API

Delivered as three pull requests, each reviewable alone. Design: decision 0007 and the
"P1.2 design decisions" section in it.

#### P1.2a — Engine: transformers, generators, switches (merged, pull request 8)

| #   | Acceptance criterion                                                                                   | Evidence                                            |
| --- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| 1   | Transformer impedance, ratio, taps and no-load power match closed-form solutions                       | `test_transformer.py`                               |
| 2   | Constant-power and voltage-controlled generators, with and without reactive limits, match closed forms | `test_generator.py`                                 |
| 3   | On nine buses the solution satisfies the power flow equations, checked without a solver                | `test_reference_networks.py`                        |
| 4   | The shipped CIGRE MV benchmark equals pandapower's copy, in data and in results                        | `test_reference_networks.py`                        |
| 5   | Every new validation rule has a documented stable code and a test                                      | `test_validation_extended.py`, `test_validation.py` |
| 6   | Open switches de-energise or open-end elements as defined; de-energised elements carry no values       | `test_switches.py`                                  |
| 7   | A faulty solution for the new elements is rejected, not returned                                       | `test_solution_checks_extended.py`                  |
| 8   | The import boundary still holds                                                                        | `test_import_boundary.py`                           |
| 9   | All P0 and P1.1 checks still pass                                                                      | CI                                                  |

Deviation from the plan: criterion 3 was planned as a comparison with published `case9`
results. No citable table could be retrieved, so it is an equation check instead; see
`docs/domain/grid-engine.md`, "Reference networks".

#### P1.2b — Database (merged, pull request 9)

Design: [decision 0008](decisions/0008-grid-persistence-and-development-tenant.md).

| #   | Acceptance criterion                                                                                                     | Evidence                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| 1   | The migration upgrades, downgrades and upgrades again, with and without data; models match the schema                    | `test_migrations.py`                              |
| 2   | The runtime role has exactly the listed grants, owns nothing, and cannot run a migration                                 | `test_roles.py`, `test_migrations.py`             |
| 3   | Without tenant context no grid table shows a row; with it a tenant sees only its own                                     | `test_grid_tenant_isolation.py`                   |
| 4   | A tenant cannot create, change, delete or reference another tenant's rows; references cannot leave their grid            | `test_grid_tenant_isolation.py`                   |
| 5   | Tenant context does not survive a commit, rollback or error on a pooled connection; concurrent tenants do not mix        | `test_tenant_transaction.py`                      |
| 6   | The database rejects every invalid single row, including NaN and infinity in every numeric column                        | `test_grid_constraints.py`                        |
| 7   | A grid is stored and read back unchanged, and its hash equals the stored hash                                            | `test_grid_repository.py`, `test_grid_mapping.py` |
| 8   | Of two concurrent writers exactly one wins; a stale version changes nothing                                              | `test_grid_repository.py`                         |
| 9   | The seed is deterministic and idempotent, refuses other environments, and the seeded grid solves to the benchmark result | `test_seed.py`                                    |
| 10  | The development tenant needs both an allowed environment and an explicit setting                                         | `test_tenancy.py`                                 |
| 11  | All earlier checks still pass                                                                                            | CI                                                |

#### P1.2c — Grid API (merged, pull request 10)

Design: [decision 0009](decisions/0009-grid-api-contract.md).

| #   | Acceptance criterion                                                                                                 | Evidence                                       |
| --- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 1   | Create, list, read, rename, describe and delete grids; read and replace topologies; read and change assets           | `test_grid_api.py`                             |
| 2   | After every kind of write the stored hash equals the hash of the model rebuilt from the rows                         | `test_grid_api.py`                             |
| 3   | Renaming changes the hash; description and diagram positions do not; every write bumps the version                   | `test_grid_api.py`                             |
| 4   | An invalid grid is refused on create, replace and asset change, and the database is unchanged row for row            | `test_grid_api_writes.py`                      |
| 5   | A failure after the old elements are deleted rolls back everything                                                   | `test_grid_api_writes.py`                      |
| 6   | Missing, malformed and stale `If-Match` give 428, 400 and 412 and change nothing; of two concurrent writers one wins | `test_grid_api_writes.py`                      |
| 7   | Strict schemas refuse unknown fields, text booleans, NaN, blank names, client ids and `data_origin`                  | `test_grid_api_writes.py`                      |
| 8   | Another tenant's grid is indistinguishable from a missing one for every route; no response carries tenant or row ids | `test_grid_api_isolation.py`                   |
| 9   | The grid API does not exist in staging and production; without a development tenant it answers 503 without a query   | `test_grid_api_isolation.py`, `test_system.py` |
| 10  | Body and element limits are enforced                                                                                 | `test_grid_api_writes.py`                      |
| 11  | The API exposes exactly the allowed routes; the platform endpoints stay read-only                                    | `test_system.py`                               |
| 12  | The seeded demonstration grid is readable through the API with the benchmark's hash                                  | `test_grid_api_isolation.py`                   |
| 13  | All earlier checks still pass                                                                                        | CI                                             |

### P1.3 — Simulation

The five scenarios (normal operation, demand increase, transformer overload, feeder outage,
renewable generation); job lifecycle; a separate worker; `sim` schema; results API; stored
input snapshots and hashes. Design: [decision 0010](decisions/0010-simulation-domain-and-job-lifecycle.md)
and [docs/domain/simulation.md](domain/simulation.md).

#### P1.3a — Simulation domain and job lifecycle (merged, pull request 11)

| #   | Acceptance criterion                                                                                             | Evidence                                              |
| --- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| 1   | Every pair of job states is legal or refused identically in Python and in the database                           | `test_simulation_domain.py`, `test_sim_schema.py`     |
| 2   | Terminal jobs and submitted columns cannot change for any role; snapshots and scenarios are immutable            | `test_sim_schema.py`                                  |
| 3   | A snapshot reads back as the same grid, its hash is the grid hash, and damaged content cannot be stored          | `test_snapshots.py`, `test_sim_schema.py`             |
| 4   | Submission captures the grid version and hash; base and input snapshots are stored; the stored grid is untouched | `test_simulation_submission.py`                       |
| 5   | A grid write and a submission never interleave: each waits for the other                                         | `test_simulation_submission.py`                       |
| 6   | Stale version, missing scenario keys and a scenario that breaks the grid are refused and store nothing           | `test_simulation_submission.py`                       |
| 7   | Each scenario modification behaves as specified, deterministically; invalid documents are refused                | `test_scenarios.py`                                   |
| 8   | Idempotency keys return the first job, refuse a different request, and hold under concurrency                    | `test_simulation_submission.py`                       |
| 9   | Deleting the grid or scenario keeps the job, its snapshots and its specification                                 | `test_simulation_submission.py`                       |
| 10  | Row-level security on every sim table; no cross-tenant reads, writes or references                               | `test_sim_schema.py`, `test_simulation_submission.py` |
| 11  | Exact grants; the API role can only submit and cancel a queued job                                               | `test_roles.py`, `test_sim_schema.py`                 |
| 12  | Failure codes come from the catalogue only                                                                       | `test_simulation_domain.py`, `test_sim_schema.py`     |
| 13  | Submission never loads the solver                                                                                | `test_simulation_submission.py`                       |
| 14  | The migration downgrades with data and upgrades again; all earlier checks pass                                   | `test_migrations.py`, CI                              |

CI run 43419018212 on the merge commit passed all five jobs: engine 422, API unit 166 and
integration 534 tests.

#### P1.3b — Worker (merged, pull request 12)

Design: [decision 0011](decisions/0011-simulation-worker.md).

| #   | Acceptance criterion                                                                                                                 | Evidence                                            |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| 1   | Concurrent workers never claim the same job; jobs are taken oldest first across tenants                                              | `test_worker_functions.py`                          |
| 2   | The worker role reads and writes no table; only it may run the worker functions, which are definer-safe                              | `test_worker_functions.py`, `test_roles.py`         |
| 3   | Calls about a job need its tenant context and its live lease; a stale worker changes nothing                                         | `test_worker_functions.py`                          |
| 4   | Expired leases are requeued with the attempt recorded; after the last attempt the job fails `worker_lost`                            | `test_worker_functions.py`                          |
| 5   | Heartbeats extend only a live lease held by the caller                                                                               | `test_worker_functions.py`                          |
| 6   | Completion stores the result and the terminal state together; non-convergence stores no result                                       | `test_worker_functions.py`                          |
| 7   | Failure messages can only be catalogue entries                                                                                       | `test_worker_functions.py`                          |
| 8   | A solved job's stored result is reproduced from its stored input alone                                                               | `test_worker_process.py`                            |
| 9   | A timeout kills the solver process; a dying solver is retried, then reported lost                                                    | `test_worker_process.py`                            |
| 10  | SIGTERM: idle exit, a short job finishes, a long one is released; SIGKILL: the next worker recovers it and the orphaned solver exits | `test_worker_process.py`                            |
| 11  | An unreachable database is waited for; a mismatched schema stops the worker                                                          | `test_worker_process.py`                            |
| 12  | Neither the API nor the worker parent loads the solver                                                                               | `test_import_boundary.py`, `test_worker_process.py` |
| 13  | The deployed worker solves a submitted job and stops cleanly on SIGTERM                                                              | CI job "Worker"                                     |
| 14  | All earlier checks still pass                                                                                                        | CI                                                  |

CI run 43426182696 on the merge commit (`91440b9`) passed all six jobs: engine 476, API unit
166 and integration 576, worker processes 13, the Compose smoke test (job completed and
converged with one result row; worker exit code 0 on SIGTERM), web 39 and end-to-end 7.

#### P1.3c — Reproduction, result summaries, retention (merged)

Design: [decision 0012](decisions/0012-reproduction-summaries-and-retention.md).

| #   | Acceptance criterion                                                                                                                                     | Evidence                                              |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| 1   | A correct stored result reproduces as `match`, also after a solver version change                                                                        | `test_reproduction.py`                                |
| 2   | A stored result the software does not compute is `mismatch`; with another solver version `differs_after_engine_change`                                   | `test_reproduction.py`                                |
| 3   | Non-convergence reproduces as non-convergence, with no result                                                                                            | `test_reproduction.py`                                |
| 4   | A damaged input is `snapshot_corrupt`; a missing result `result_missing`; failed or cancelled jobs `not_reproducible`; none is solved                    | `test_reproduction.py`                                |
| 5   | The database decides the verdict; reproduction is tenant-scoped; reproductions are append-only                                                           | `test_reproduction.py`                                |
| 6   | The command exits non-zero on an integrity problem                                                                                                       | `test_reproduction.py`, CI                            |
| 7   | Summaries report totals, extremes and counts without invented limits; no values when not converged                                                       | `test_result_summaries.py`, `test_results_service.py` |
| 8   | Results are read through the API role, hash-checked, tenant-scoped                                                                                       | `test_results_service.py`                             |
| 9   | Retention: dry run changes nothing; only finished jobs before the cutoff go; shared snapshots, grids and scenarios stay; a failure rolls that job back   | `test_retention.py`                                   |
| 10  | Worker: bad configuration is `invalid_input`; a solver that cannot start stops the worker safely; engine version drift is logged; statement timeout 30 s | `test_worker_fixes.py`, `test_reproduction.py`        |
| 11  | All earlier checks still pass                                                                                                                            | CI                                                    |

PR 13 merged as `2c088ef`. CI run 43603454270 on the merge commit passed all six jobs:
engine 492, API unit 173 and integration 603, worker processes 13, end-to-end 7, and the
Compose reproduction reported `"verdict": "match"` with worker exit code 0 on SIGTERM.

#### P1.3d — Simulation API (merged)

Design: [decision 0013](decisions/0013-simulation-api-contract.md). No migration.

| #   | Acceptance criterion                                                                                                                         | Evidence                                     |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| 1   | Scenarios are created, read, listed and deleted; invalid ones report the engine's codes and store nothing                                    | `test_simulation_api.py`                     |
| 2   | Submission returns `202` with a queued job matching the grid; refusals (412, 400, 404, 422) store nothing                                    | `test_simulation_api.py`                     |
| 3   | An `Idempotency-Key` replays the first job (`200`, `Idempotent-Replayed`), refuses a different request, and makes one job under concurrency  | `test_simulation_api.py`                     |
| 4   | Jobs are listed newest first with grid, status and date filters; the source status follows the grid                                          | `test_simulation_api.py`                     |
| 5   | Only queued jobs can be cancelled; a cancel racing a claim has one winner                                                                    | `test_simulation_api.py`                     |
| 6   | Results: converged gives summary and document; not converged no values; others `409`; damaged data `500` with no values                      | `test_simulation_api.py`                     |
| 7   | Reproduction history is read-only and newest first; reading it reproduces nothing                                                            | `test_simulation_api.py`                     |
| 8   | No response holds organisation, lease, worker, fingerprint or key fields                                                                     | `test_simulation_api.py` (unit, integration) |
| 9   | Another tenant's ids give the same `404` as random ids and change nothing; no tenant gives `503`; staging and production have no such routes | `test_simulation_api.py`, `test_system.py`   |
| 10  | The API process never loads the solver                                                                                                       | `test_simulation_api.py`                     |
| 11  | Over HTTP, the deployed API queues a job, the deployed worker solves it, and its reproduction is a `match`                                   | CI job "Worker"                              |
| 12  | All earlier checks still pass                                                                                                                | CI                                           |

PR 14 merged as `75c14cd`. CI run 43609180281 on the merge commit passed all six jobs:
engine 498, API unit 205 and integration 624, worker processes 13, web 39, end-to-end 7, and
the HTTP flow in the Worker job (job converged, result HTTP 200, reproduction `match`;
worker exit code 0).

### P1.4 — Web

2D network view, asset tables, running a scenario and inspecting results; end-to-end tests.
Five PRs, in dependency order. Design: [decision 0014](decisions/0014-web-application-architecture.md).
No backend change is planned; the web app uses the P1.2c and P1.3d APIs as they are.

#### P1.4a — API client, shared UI, grid list and grid page (merged)

| #   | Acceptance criterion                                                                                                          | Evidence                                      |
| --- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| 1   | Stored grids are listed with their synthetic origin, version and element counts; an empty list says how to seed the demo grid | `grids.spec.ts`, `grid-list-view.test.tsx`    |
| 2   | A grid page shows metadata, version and topology hash, labelled synthetic                                                     | `grids.spec.ts`, `grid-detail-view.test.tsx`  |
| 3   | Unreachable API, routes absent, no development tenant, invalid id and unknown grid each have their own state                  | `client.test.ts`, view tests, `grids.spec.ts` |
| 4   | Decoders refuse payloads of the wrong shape                                                                                   | `grids.test.ts`, `topology.test.ts`           |
| 5   | The development-tenant notice is shown wherever tenant data is shown                                                          | view tests, `grids.spec.ts`                   |
| 6   | No new runtime dependency; the bundle check passes; all earlier checks still pass                                             | CI                                            |

PR 15 merged as `7937449`. CI run 43619109149 on the merge commit passed all six jobs; the
end-to-end job seeded the demonstration grid and passed 12 tests.

#### P1.4b — 2D network explorer (merged)

The stored network as an SVG diagram on the grid page, with an element list for the
keyboard and an inspector for the selected element. Layout rules: decision 0014, section 10.

| #   | Acceptance criterion                                                                                                                      | Evidence                                                       |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| 1   | Stored positions are used when every bus has one (y flipped, scaled); otherwise every bus is placed by the fallback layout, with a notice | `layout.test.ts`, `network-explorer.test.tsx`                  |
| 2   | The fallback layout is deterministic, starts at external-grid buses and keeps separate parts apart                                        | `layout.test.ts`                                               |
| 3   | Each line, transformer and bus coupler is one connection between its own buses; parallel connections are separated                        | `layout.test.ts`, `graph.test.ts`                              |
| 4   | A switch is drawn on its element at its own bus; a broken reference is listed and nothing is drawn                                        | `layout.test.ts`, `graph.test.ts`, `network-explorer.test.tsx` |
| 5   | Open and closed switches and out-of-service elements differ by shape or dash and by name                                                  | `network-canvas.test.tsx`                                      |
| 6   | Selecting in the diagram or the list shows the element's stored values; missing values are "not set", never zero; references select       | `element-inspector.test.tsx`, `network.spec.ts`                |
| 7   | The selection is kept in the address; the keyboard alone reaches and selects any element                                                  | `network-explorer.test.tsx`, `network.spec.ts`                 |
| 8   | Loading, API failures, wrong shapes, no buses and a version mismatch each have their own state                                            | `network-explorer.test.tsx`                                    |
| 9   | Labelled synthetic; no live measurements or electrical state claimed or computed                                                          | `network-explorer.test.tsx`, `network.spec.ts`                 |
| 10  | The seeded CIGRE MV grid is drawn with all its elements and its three open switches                                                       | `network.spec.ts`                                              |
| 11  | No new dependency; all earlier checks still pass                                                                                          | CI                                                             |

PR 16 merged as `3f728e3`. CI run 43673794414 on the merge commit passed all six jobs.

#### P1.4c — Asset management (merged)

Overview, Assets and Settings tabs for each grid. Editing rules: decision 0014, section 11.

| #   | Acceptance criterion                                                                                        | Evidence                                                                                        |
| --- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1   | Overview, Assets and Settings tabs with their own addresses; `/assets` chooses a grid                       | `grid-workspace.test.tsx`, `grid-list-view.test.tsx`                                            |
| 2   | Every element is listed; type, state and text filters work alone and together and are kept in the address   | `filter.test.ts`, `asset-inventory.test.tsx`, `assets.spec.ts`                                  |
| 3   | Only the name and either the service state or a switch's model position can be edited                       | `asset-edit-form.test.tsx`                                                                      |
| 4   | Name and description limits as in the API; Save disabled until something changes; Cancel sends nothing      | `assets.test.ts`, `asset-edit-form.test.tsx`, `grid-settings.test.tsx`                          |
| 5   | A state or model-position change is reviewed, with the simulation-only notice, before it is saved           | `asset-edit-form.test.tsx`, `assets.spec.ts`                                                    |
| 6   | Every write sends If-Match; after saving, grid and network reload together and the diagram shows the change | `asset-inventory.test.tsx`, `assets.spec.ts`                                                    |
| 7   | A stale version keeps the draft, shows the current version, overwrites nothing and never resends by itself  | `asset-edit-form.test.tsx`, `assets.spec.ts`                                                    |
| 8   | Engine refusals and name conflicts are explained; nothing is stored                                         | `asset-edit-form.test.tsx`, `grid-settings.test.tsx`, `assets.spec.ts`, `grid-settings.spec.ts` |
| 9   | Deleting needs the exact name, explains what jobs keep, sends If-Match and returns to the list              | `delete-grid.test.tsx`, `grid-settings.spec.ts`                                                 |
| 10  | The keyboard alone filters, selects and edits                                                               | `assets.spec.ts`                                                                                |
| 11  | End-to-end tests that write use their own copies of the demonstration grid                                  | `e2e/support/grid-copy.ts`                                                                      |
| 12  | No new dependency, no backend change; all earlier checks still pass                                         | CI                                                                                              |

PR 17 merged as `fb200c1`. CI run 43678159611 on the merge commit passed all six jobs.

#### P1.4d — Simulation workspace (implementation complete; pending review, CI verification and merge)

Jobs, New simulation and Scenarios tabs under `/simulations`, and a page per job. Rules:
decision 0014, section 12.

| #   | Acceptance criterion                                                                                                                                         | Evidence                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------- |
| 1   | Scenarios are listed with their changes in words, created from a form with the API's and engine's rules, and deleted after confirmation                      | `scenario-form.test.tsx`, `scenarios-view.test.tsx`, `simulations.spec.ts` |
| 2   | A submission sends the grid version on screen as If-Match and one idempotency key per distinct request                                                       | `simulations.test.ts`, `new-simulation-form.test.tsx`                      |
| 3   | A stale grid, an inapplicable scenario and solver options outside the engine's bounds are explained; nothing is queued                                       | `new-simulation-form.test.tsx`                                             |
| 4   | The job page follows the job (1 s, then 2 s, then 5 s), pauses while hidden, stops at a final status, and survives a failed refresh                          | `use-polling.test.tsx`, `simulations.spec.ts`                              |
| 5   | Queued, running, completed (converged or not), failed and cancelled each say what they mean in words; no values are promised for a run that did not converge | `job-view.test.tsx`, `simulations.spec.ts`                                 |
| 6   | Only a queued job offers cancel, after confirmation; a refused cancel is explained                                                                           | `job-view.test.tsx`, `simulations.spec.ts`                                 |
| 7   | The job list names grids and scenarios, filters by grid and status in the address, and refreshes only on request                                             | `jobs-view.test.tsx`, `simulations.spec.ts`                                |
| 8   | Submitted from the grid page, a simulation of the seeded grid is solved by the real worker and shown as converged                                            | `simulations.spec.ts` (CI end-to-end job runs the worker)                  |
| 9   | No new dependency, no backend change; all earlier checks still pass                                                                                          | CI                                                                         |

#### P1.4e — Results and reproductions (not started)

Summary and element tables from the stored result, no values for a run that did not
converge, reproduction history; loading on the diagram only when the topology is unchanged.

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
