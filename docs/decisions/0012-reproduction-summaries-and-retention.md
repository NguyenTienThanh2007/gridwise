# 0012 — Reproduction, result summaries and retention

- Status: accepted (P1.3c, 2026-11-14). Extends decisions 0010 and 0011.

## Context

P1.3b stores each converged job's result with its completion. A stored result is only
trustworthy if it can be computed again from the stored input and compared, if it can be
read compactly, and if old simulations can be removed without breaking anything that is
kept. The P1.3b post-merge audit also left four small worker items (L1–L4).

## Decisions

### 1. Reproduction runs on the worker side and the database decides the verdict

`python -m gridwise_worker.reproduce` (`make reproduce`) re-solves finished jobs with the
worker's credentials and solver process; nothing reproduces in an HTTP request. For each
job it reads the stored input (`sim.reproduction_input`, under the job's tenant context),
verifies the snapshot's hash, solves with the job's exact configuration, and reports what it
got to `sim.record_reproduction`. That function compares with what is stored and returns
the verdict; the caller cannot choose it.

| Verdict                       | When                                                                                |
| ----------------------------- | ----------------------------------------------------------------------------------- |
| `match`                       | Same outcome and, for converged jobs, the same `result_hash`                        |
| `mismatch`                    | Different, with the same engine and solver versions: an integrity alarm             |
| `differs_after_engine_change` | Different, with another engine or solver version: reported, expected possible drift |
| `result_missing`              | Completed and converged, but no stored result (not solved)                          |
| `not_reproducible`            | The job failed or was cancelled (not solved)                                        |
| `snapshot_corrupt`            | The stored input does not match its hash (not solved)                               |
| `reproduction_failed`         | The reproduction itself did not finish (solver error, timeout)                      |

Every reproduction is a row in `sim.reproductions`, append-only and readable by the API role
for its own tenant. `sim.reproduction_candidates` lists completed jobs never reproduced,
across tenants, ids only. The command exits non-zero on `mismatch`, `result_missing`,
`snapshot_corrupt` or `reproduction_failed`.

Results are compared by the rounded `result_hash`, not by exact bytes: identical input can
differ in the last bits of a float when elements arrive in another order.

The worker role is trusted to report honestly what it computed; the database guarantees
everything else (which job, which stored values, which verdict follows).

### 2. Summaries are computed on read

`gridwise_grid_engine.result_summaries.summarize_result_document` (schema
`gridwise.result-summary/1`) turns a stored result into totals, voltage extremes, highest
line and transformer loading with their keys, the number of lines and transformers above
100 % of their own rating, and de-energised counts. It adds no limits the engine does not
model. A job that did not converge has a summary with no values. `services/results.py`
reads results through the API role, checks the document's hash, and summarises; P1.3d
exposes it. Nothing new is stored, so results stay immutable and nothing needs backfilling.

### 3. Engine versions are recorded and reported, never refused

`sim.claim_next_job` now also returns the engine version a job was submitted with, and the
worker logs `engine_version_differs` when it computed with another. Both versions stay on
the job; reproduction reports drift as its own verdict. Refusing such jobs could leave them
queued forever after an upgrade.

### 4. Retention is manual and safe

`python -m gridwise_api.retention --finished-before <time with zone> [--organization]
[--apply]` runs as the owner role and is a dry run unless `--apply` is given. Only jobs that
ended before the cutoff are eligible, and each is re-checked under a row lock. Per job, in
one transaction: its reproductions, attempts and result, the job, and the snapshots no other
job refers to. Grids and scenarios are never touched. If anything fails, that job's
deletion rolls back as a whole. Nothing is deleted automatically.

### 5. Worker fixes from the P1.3b audit

- **L1:** a configuration the engine refuses is `invalid_input`, not `solver_failed`.
- **L2:** a solver process that cannot start stops the worker with exit code 3 before it
  claims anything; one that cannot restart in the middle of a job releases the job first.
- **L3:** the health check is meant to fail while the database is unreachable for longer
  than its window: the worker is not working then. Documented, unchanged.
- **L4:** every worker connection has `statement_timeout = 30s`, so no call can hang the
  loop and its heartbeat.

## Consequences

- Migration `0005` adds `sim.reproductions` and three functions, and recreates
  `sim.claim_next_job` with one more output column (same arguments).
- CI's Worker job reproduces the job its smoke test solved.
