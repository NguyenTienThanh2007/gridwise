# 0013 — Simulation API contract

- Status: accepted (P1.3d, 2026-11-14). Extends decisions 0009, 0010, 0011 and 0012.

## Context

P1.3a–c built the simulation domain, the worker, reproduction and result summaries behind
services, with no HTTP surface. P1.3d exposes them over HTTP for the web app (P1.4), without
changing the engine, the worker, the database or the safety boundary. No migration is
needed: the API role already has exactly the privileges these routes use.

## Decisions

### 1. Ten routes, local and test only

| Method and path                                  | Purpose                                     | Success                               |
| ------------------------------------------------ | ------------------------------------------- | ------------------------------------- |
| `POST /api/v1/scenarios`                         | Create a scenario (immutable)               | `201` + `Location`                    |
| `GET /api/v1/scenarios`                          | List scenarios                              | `200`                                 |
| `GET /api/v1/scenarios/{scenario_id}`            | Read one                                    | `200`                                 |
| `DELETE /api/v1/scenarios/{scenario_id}`         | Delete; jobs keep their own copy            | `204`                                 |
| `POST /api/v1/grids/{grid_id}/simulations`       | Submit: snapshot, apply the scenario, queue | `202` + `Location`; `200` on a replay |
| `GET /api/v1/simulations`                        | List jobs, newest first                     | `200`                                 |
| `GET /api/v1/simulations/{job_id}`               | Status, provenance, attempts                | `200`                                 |
| `POST /api/v1/simulations/{job_id}/cancel`       | Cancel a queued job                         | `200`                                 |
| `GET /api/v1/simulations/{job_id}/result`        | Summary and stored result document          | `200`                                 |
| `GET /api/v1/simulations/{job_id}/reproductions` | Reproduction history, newest first          | `200`                                 |

Like the grid API (decision 0009) they are registered only when `GRIDWISE_ENVIRONMENT` is
`local` or `test`, act for the fixed development tenant, and answer `503` before any query
when none is configured. This is a choice of tenant, not authentication or access control;
that arrives with P6. Every route is in the allow-list of `tests/unit/test_system.py`.

Scenario routes are included because submission refers to a scenario id; without them only
normal operation could be simulated over HTTP.

### 2. Submission returns at once; the client polls

Submitting runs `SimulationService.submit` (decision 0010) and returns `202` with the job,
`queued`. No power flow runs in a request and the API process never imports the solver
(tested in a fresh interpreter). The client follows the job's `self` link, for example once
a second, until its status is `completed`, `failed` or `cancelled`. There are no push
notifications in P1.

`If-Match` is optional on submission: submitting never changes the grid. When sent, it must
be the grid's current version (`412` with the current `ETag` otherwise; malformed, weak,
list or `*` is `400`). Without it, the job captures whatever version is current.

### 3. Idempotency

An optional `Idempotency-Key` header (1–200 printable ASCII characters, no spaces: the same
rule as the database's check) makes submission safe to retry:

- the same key with the same request returns the original job with `200` and
  `Idempotent-Replayed: true`;
- the same key with a different request is `422 idempotency_key_reused`;
- concurrent submissions with one key create one job (the database's unique constraint).

"The same request" is the request fingerprint of decision 0010: grid, scenario, configuration
and expected version.

### 4. What a job looks like

`source` gives the grid, version and topology hash the job captured, and a `status`:
`current` (the grid is still at that version), `changed` (it has a later version) or
`deleted`. It is read in the same transaction as the job. The job is unaffected either way:
it solves its own snapshot.

`scenario` carries the stored specification the job applied (its `id` is `null` for normal
operation or once the scenario is deleted), `configuration` the solver options and their
hash, `engine` the requested and executed engine and solver versions, and
`input_snapshot_hash` the content hash of the exact input. Failures show the catalogue's code
and message only (decision 0011). The detail adds `attempts`.

Never in any response: `organization_id`, lease token and expiry, heartbeat, `worker_id`
(also not in attempts or reproductions; it names hosts and processes), the request
fingerprint, the idempotency key, and internal snapshot ids. Unit tests check both the
representations and the OpenAPI schemas.

### 5. Results

| Job                                  | Response                                                                    |
| ------------------------------------ | --------------------------------------------------------------------------- |
| Completed, converged                 | `200`: summary (`gridwise.result-summary/1`) and the stored result document |
| Completed, not converged             | `200`: `result_hash` and `result` `null`, summary with every value `null`   |
| Queued, running, failed or cancelled | `409 result_not_available`, the status in `details`                         |
| Stored document fails its check      | `500 internal_error`, logged with the job id; no values returned            |

The summary and the document come in one response (about 30 KB for CIGRE MV). A separate
document route can follow if size becomes a concern.

### 6. Cancellation and reproductions

Only a queued job can be cancelled (`409 job_not_cancellable` with the current status
otherwise). A cancel racing a worker's claim has one winner, decided by the database.

The reproduction history is read-only. The API never triggers a reproduction: reproducing
means solving, which stays in the worker (`make reproduce`).

### 7. Errors

| Condition                                                       | Status | `code`                                                  |
| --------------------------------------------------------------- | ------ | ------------------------------------------------------- |
| Grid, job or scenario (in the path) missing or another tenant's | 404    | `grid_not_found`, `job_not_found`, `scenario_not_found` |
| Scenario in the body missing or another tenant's                | 422    | `scenario_not_found`                                    |
| Stale `If-Match`                                                | 412    | `version_conflict` (with `ETag`)                        |
| Malformed `If-Match` / `Idempotency-Key`                        | 400    | `invalid_if_match` / `invalid_idempotency_key`          |
| Key reused for another request                                  | 422    | `idempotency_key_reused`                                |
| Scenario document invalid                                       | 422    | `scenario_invalid` (engine codes in `details`)          |
| Scenario names elements the grid lacks                          | 422    | `scenario_not_applicable`                               |
| Simulated grid invalid / too large                              | 422    | `simulated_grid_invalid` / `grid_too_large`             |
| Scenario name already used                                      | 409    | `scenario_name_conflict`                                |
| Request schema, configuration outside the engine's bounds       | 422    | `validation_error`                                      |
| Stored data fails its integrity check                           | 500    | `internal_error`                                        |

Another tenant's job, grid or scenario is the same `404` as a random id, with the same
message.

### 8. The worker CI job runs the flow over HTTP

The CI Worker job submits through the deployed API container, waits for the deployed worker,
reads the result, runs `reproduce --pending` and reads a `match` from the reproduction
history, all over HTTP (`scripts/worker_smoke.py http-*`). It is the only check of API and
worker together as deployed.

## Consequences

- The web app (P1.4) can submit and follow simulations with no backend change.
- The safety boundary is unchanged: these routes store scenarios and queued jobs, cancel
  queued jobs and read results. Scenario `set_switch` and `set_in_service` change the
  simulated copy only, as the OpenAPI operations state.
- Scenarios have no per-tenant quota yet; the request body and element limits of the grid
  API apply. Quotas come with authentication (P6).
