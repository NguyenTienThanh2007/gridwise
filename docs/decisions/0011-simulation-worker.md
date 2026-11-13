# 0011 — Simulation worker

- Status: accepted (P1.3b, 2026-11-13). Extends decision 0010.

## Context

Decision 0010 made jobs submittable and their lifecycle enforced by the database, and
placed solving in a separate worker. P1.3b builds that worker. The preflight audit found
that the lifecycle trigger restricts only the API role (any other role could rewrite
leases), that completion needs somewhere to put results, and that Python 3.13's process
pool cannot stop a task once it has started.

## Decisions

### 1. The worker reaches the database only through five functions

| Function             | Does                                                                                                                                                         |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `sim.claim_next_job` | Requeue or fail jobs whose lease expired (recording the attempt), then take the oldest queued job with `FOR UPDATE SKIP LOCKED` and a new random lease token |
| `sim.heartbeat_job`  | Extend a live lease the caller holds                                                                                                                         |
| `sim.complete_job`   | Store the result (converged only) and the terminal status in one transaction                                                                                 |
| `sim.fail_job`       | Record a failure; the message comes from `sim.failure_catalogue`                                                                                             |
| `sim.release_job`    | Give the job back: requeued while attempts remain, otherwise `failed / worker_lost`                                                                          |

Every call about a held job requires its lease token, an unexpired lease by the database's
clock, and the transaction's tenant context set to the job's organisation. A worker whose
lease was taken over gets `false` and changes nothing. The functions are
`SECURITY DEFINER`, owned by `gridwise_owner`, with `search_path = pg_catalog, pg_temp` and
fully qualified names; only `gridwise_worker` may execute them.

The role `gridwise_worker` (LOGIN, NOINHERIT, no SUPERUSER, BYPASSRLS, CREATEDB or
CREATEROLE) holds `USAGE` on `sim`, `EXECUTE` on the five functions and `SELECT` on
`alembic_version`, and nothing else: it cannot read or write any table.

### 2. Results arrive with completion

`sim.results` holds one immutable result per converged job: the engine's full result as
canonical text (`gridwise.power-flow-result-document/1`, exact values, `null` for
de-energised elements), its SHA-256 checked by the database, and the engine's
`result_hash`. It is written only by `sim.complete_job`, in the same transaction as the
terminal status. A job that did not converge has no row. The API role may read results of
its own tenant (row-level security).

### 3. Failure messages come from the database

`sim.failure_catalogue` holds the six codes and messages; a foreign key makes every failed
job's code and message a catalogue entry, word for word. A caller of `fail_job` passes a
code only. `worker_lost` cannot be reported: only lease expiry or release produces it.

### 4. The solver runs in a child process that can be killed

The worker parent claims jobs and talks to the database; it never imports a numerical
library. It starts one long-lived child with the `spawn` method (never `fork`, which Linux
uses by default: the parent holds connections and threads). The child imports the adapter
once, verifies each input snapshot's hash, solves, and answers with the outcome or a
failure code; it never opens a database connection. A child that loses its parent exits
by itself.

`ProcessPoolExecutor` was rejected: in Python 3.13 it cannot stop a task that has started,
so a timed-out solve would keep its CPU and memory.

### 5. Lease, retry and timeout rules

| Event                               | Result                                                                                                                         |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Solved                              | `completed`, outcome `converged` (with result) or `not_converged`                                                              |
| Input or solver failure             | `failed` with its code; never retried                                                                                          |
| Over the time limit (default 120 s) | The child is killed; `failed / execution_timeout`; not retried                                                                 |
| The child dies                      | Released; requeued while attempts remain (default 3), then `worker_lost`                                                       |
| The worker dies (lease expires)     | Requeued by the next claim; after the last attempt `failed / worker_lost`                                                      |
| SIGTERM                             | Stop claiming; the current job may finish within 20 s; otherwise the child is killed and the job released (the attempt counts) |
| Database unavailable                | Back off (1 s doubling to 30 s); a result is kept and reported while the lease can still be valid, otherwise dropped           |

The lease is 60 s and the heartbeat 10 s; all of these are configurable.

### 6. Deployment

One image serves the API, the migrations and the worker. The worker is a Compose service
behind the `worker` profile (`make up-worker`), limited to 768 MB and one CPU for a 4 GB
development VM, with `stop_grace_period: 30s`. Its health check fails when the loop has not
touched its health file for 30 s. At start it refuses a schema revision other than the one
it was built for.

New database volumes create the role from the init script; existing ones run
`make db-worker-role` (idempotent). Migration `0004` stops with that instruction if the role
is missing.

### 7. Smaller changes from the audit

- A queued job must have an attempt left (`attempt < max_attempts`), so it can always be
  claimed.
- Partial indexes on queued jobs by age and running jobs by lease expiry, for claiming and
  reaping across tenants.

## What this does not establish

- Throughput beyond one solve at a time per worker container.
- Fair scheduling between tenants: jobs are taken oldest first.
- Cancelling a running job.

## Consequences

- P1.3c narrows to reproduction checks, result summaries and retention.
- The worker's tests start real processes and send real signals; CI runs them on Linux in
  their own job, together with a Compose smoke test of the deployed worker.
