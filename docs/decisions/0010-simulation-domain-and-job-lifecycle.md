# 0010 — Simulation domain and job lifecycle

- Status: accepted (P1.3a, 2026-11-13). Amends decision 0007 §7 (where solves run).

## Context

P1.3 runs power flows against stored grids. A result is only useful if it can be traced to
exactly what was computed and computed again. Solving is CPU-bound and loads large
numerical libraries, so it must never run in an HTTP request. P1.3a fixes the domain and
the database; the worker (P1.3b), results (P1.3c) and the HTTP API (P1.3d) follow.

## Decisions

### 1. A separate worker, not a pool inside the API (amends 0007 §7)

Decision 0007 planned a process pool owned by the API container. The owner's P1.3
requirements say worker execution must be isolated from API processes, and a pool inside
the API loses its jobs whenever the API restarts. Solves therefore run in a separate worker
service (P1.3b), from the same image, which claims jobs from the database. No broker is
introduced: the queue is the `sim.jobs` table. The API process never imports the solver,
as before, and only the worker package may import the adapter.

### 2. Jobs solve an immutable snapshot, never the live grid

At submission, in one tenant transaction, the grid row is share-locked (writers wait), its
rows are rebuilt into the engine's model and checked against its stored `topology_hash`,
the scenario is applied to a copy, and the result is validated with the engine. Two
snapshots are stored: the **base** snapshot (the grid as stored) and the **input** snapshot
(what the solver will get). The job records the grid's id, version and hash.

A snapshot is the engine's canonical grid text (`gridwise.grid/2`), so its SHA-256 is the
grid hash. It is stored as text, not JSONB, so the exact bytes are kept. The database
itself checks `content_hash = sha256(document)`, and a trigger refuses every update, for
every role including the owner. Snapshots are deduplicated per tenant by hash.

Diagram positions are not part of snapshots: they are not electrical.

### 3. What happens to a job when its sources change

Nothing: a job reads only its snapshots. A changed grid leaves the job's recorded version
and hash as they were. A deleted grid or scenario clears only the job's reference to it
(`ON DELETE SET NULL (column)`, PostgreSQL 15+); the job, its snapshots and its copy of the
scenario specification remain.

### 4. Scenarios

A scenario is an immutable, tenant-owned list of modifications (`gridwise.scenario/1`):
`scale_loads`, `scale_generation`, `set_in_service`, `set_switch`. It is not tied to one
grid; the keys it names are checked against the grid at submission. The engine applies it
as a pure function. A job stores its own copy of the specification, so reproducing a job
never re-runs scenario code: it solves the stored input snapshot.

Five presets cover the roadmap's study cases. Their factors are illustrative assumptions,
not measured or forecast values. A switch set in a scenario changes the simulated copy only.

### 5. Lifecycle

```
queued ──claim──▶ running ──▶ completed (outcome: converged | not_converged)
  │   ◀──lease expired──┘ └──▶ failed (failure_code)
  └──cancel──▶ cancelled
```

The legal moves are stored in `sim.job_transitions` and enforced by a trigger for every
role; a test keeps that table identical to the Python domain. The trigger also freezes
every submitted column and every terminal job. The runtime role may make exactly one move,
`queued → cancelled`, and holds column privileges for nothing else.

Consistency between status and the other columns is a set of row checks: an outcome
exactly when completed, a failure code exactly when failed, a lease exactly when running, a
complete record of engine and solver versions when completed.

### 6. Non-convergence is an outcome, not a failure

A run that did not converge is `completed` with outcome `not_converged` and has no values.
It is a valid, reproducible result. `failed` means the computation could not be trusted
(solver error, inconsistent solution, timeout, lost worker, damaged input).

### 7. Retries

Power flows are deterministic, so a failure caused by the input is never retried. A job is
put back in the queue only when its worker was lost (its lease expired), at most
`max_attempts` times (default 3); every attempt is recorded in `sim.job_attempts`. Timeouts
are not retried automatically. Failure messages come from a fixed catalogue, never from
exception text.

### 8. Idempotency

An optional idempotency key, unique per organisation, makes repeated submissions return
the first job. The key is bound to a fingerprint of the request (grid, scenario,
configuration, expected version); reusing it for a different request is refused. Without a
key, identical submissions are separate jobs; equal fingerprints make them recognisable.

### 9. Fingerprints

Each job records the configuration (algorithm and options, exactly) and its hash, and the
engine version at submission. The worker will record the engine version, solver name and
solver version it ran with, and the `engine_fingerprint` of all of them. The engine version
changes whenever a recorded regression hash changes; a test ties the two together.

### 10. Tenant isolation

Scenarios, snapshots, jobs and attempts are tenant-owned, with the same row-level security
policy as the grid schema, composite foreign keys, and `organization_id` first in every
unique constraint. `job_transitions` is reference data. The worker (P1.3b) gets its own role
without `BYPASSRLS`, and reaches jobs of all tenants only through one claim function, then
works under the job's tenant context.

## Deviations from the approved plan

- The request fingerprint covers what the client asked for (grid id, scenario id,
  configuration, expected version), not the grid version found at submission. Otherwise a
  retried request would conflict with itself after any grid change.
- Snapshots have no `kind` column: identical content is one row whether it was used as a
  base or as an input.
- Snapshots do not carry diagram positions.
- The `renewable_generation` preset keeps units at their set-point and halves demand. A
  generation factor above 1 can exceed unit ratings, which the engine then refuses.

## Consequences

- Before P1.3b nothing runs queued jobs. Jobs can be submitted, read and cancelled.
- A new database role arrives with P1.3b; existing local volumes will need it created.
- Snapshots grow with every distinct submitted grid; retention is not decided yet.
