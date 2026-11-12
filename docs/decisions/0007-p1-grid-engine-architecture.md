# 0007 — P1 grid engine architecture

- Status: accepted (P1 planning, 2026-11-12). P1.1 implements the parts marked **done**;
  the rest is the agreed direction for P1.2–P1.4 and is confirmed when each starts.
- Amended 2026-11-12 for P1.2: see [P1.2 design decisions](#p12-design-decisions). Decision 4
  and the out-of-scope list are narrowed there.

## Context

P1 adds the electrical core: a network model, power flow, scenarios, persistence, APIs and
a network view. The P0 review flagged two things that had to be decided before any of that
is built: where CPU-bound solving runs, and how tenant isolation interacts with new tables.

Measurements that informed the decisions (pandapower 3.5.6, Python 3.13, 2026-11-12):

| Measurement                                                                   | Result                          |
| ----------------------------------------------------------------------------- | ------------------------------- |
| Resolves with the API's dependencies                                          | Yes: pandas 2.3.3, numpy 2.4.6  |
| Importing pandapower                                                          | 1.8–4 s, about 190 MB of memory |
| AC power flow, 15-bus benchmark network                                       | 15–22 ms                        |
| AC power flow, 1,354-bus case                                                 | 37 ms                           |
| Longest stall of another thread during a power flow                           | 49 ms                           |
| API image size without / with the solver stack (packaged test suites removed) | 343 MB / 705 MB                 |
| Same result hash on macOS arm64, Linux arm64 and Linux x86-64 (emulated)      | Yes                             |

## Decisions

### 1. A pure domain package — done

`packages/grid-engine` (`gridwise_grid_engine`) is a uv workspace member with no HTTP,
database or frontend dependency. Its only declared dependency is pandapower.

```
model -> validation -> topology -> solver interface -> engine -> results
                                        ^
                              adapters/pandapower_adapter   (the only pandapower import)
```

The domain layer is plain Python dataclasses. It does not use Pydantic: API schemas belong
to the API, and the engine must be usable from a worker with nothing else installed.

### 2. pandapower behind one adapter — done

Only `adapters/pandapower_adapter.py` imports pandapower (or pandas, numpy, scipy). No
pandapower type leaves it. Importing `gridwise_grid_engine` does not load pandapower. Both
rules are enforced by tests, as is the rule that the API package never imports the adapter.

Consequences: the solver can be replaced or supplemented without touching the model, and
the API process stays small and starts quickly.

### 3. Balanced AC Newton-Raphson from the start — done

Voltages and losses are the results operators need, and the DC approximation gives
neither. The cost argument for a simpler model does not hold at distribution scale (see the
measurements). Flat start on every run, so an outcome depends only on its inputs.

Not modelled in P1: unbalanced three-phase operation, dynamics, voltage-dependent loads.

### 4. The engine does not trust the solver — done

After every solve the engine checks, independently of the solver, that energised elements
have finite values, de-energised ones have none, and supply equals served load plus losses.
A solution that fails is rejected (`inconsistent_solution`), not returned. This check found
a real modelling difference during P1.1 (an in-service line on an out-of-service bus), which
is now defined explicitly: an out-of-service bus takes its attached elements with it.
Since P1.2a the checks also cover transformers and generators: a generator must deliver its
set-points, and a voltage-controlled one must hold its voltage or sit at a reactive limit.

### 5. Non-convergence is an outcome, not an exception — done

`run_power_flow` returns `converged = False` with a failure code and **no values**. The
adapter builds a new network for every solve, so no earlier solution can appear in a later
result. Invalid input raises before the solver is called.

### 6. Reproducibility by hashing — done for single solves

`grid_hash` identifies an input exactly; `result_hash` identifies a solution after rounding
to 1e-6. P1.3 stores both with every run, plus a full input snapshot and the engine and
solver versions, so a stored result can be recomputed and compared after the topology has
changed.

### 7. Execution: a process pool inside the API container — P1.3

Solving is CPU-bound and holds the interpreter lock, and loading the solver is slow and
large. Power flows will run in a small `ProcessPoolExecutor` owned by the API container;
the API's own process never imports the solver.

- The HTTP contract is asynchronous from the first version: `POST` returns `202` and a run
  resource, the client polls. A separate worker service can replace the pool later without
  an API change.
- Runs are rows (`queued → running → succeeded | failed`). A run found `running` at start-up
  is marked failed: an in-process pool loses its work on restart, and that is stated rather
  than hidden.
- No message broker, queue service or scheduler is introduced in P1.

Rejected: solving in the request thread or a thread pool (stalls the event loop and loads
the solver into the API process); a separate worker service now (more infrastructure than
millisecond-scale solves justify).

### 8. Persistence and tenancy — P1.2

- `grid` schema for topology, `sim` schema for runs and results (added to
  `MANAGED_SCHEMAS`).
- Every table follows decisions 0004 and 0006: `organization_id`, composite foreign keys, a
  row-level security policy, the `updated_at` trigger, explicit grants.
- Result tables are append-only for the runtime role (insert and select only).
- Results for de-energised elements are stored as NULL, never zero.
- Before authentication exists (P6), tenant endpoints work only in `local` and `test`
  against one fixed development organisation, with tenant context set per transaction.
  Other environments refuse them. This exercises row-level security end to end without
  presenting it as access control.

### 9. Transactions — P1.3

A run is committed as `queued` before work starts. Its results and its terminal status are
written in one transaction, so a run never has partial results.

### 10. Validation against references

- **Done (P1.1):** closed-form two-bus solutions and no-load line charging, to 1e-9 pu.
- **Done (P1.2a):** closed forms for the transformer (series impedance, ratio and taps,
  no-load power) and for both generator modes including reactive limits; switch
  equivalences; on nine buses (`case9`) the solution is put back into the power flow
  equations without a solver; the CIGRE MV benchmark and `case9` built through the GRIDWISE
  model equal pandapower's own copies in data and results.
- **Not done:** comparison with a printed table of published results. No citable table
  could be retrieved, and none is quoted from memory. The equation check replaces it.

### 11. Compatibility with later phases

- **P2 telemetry** refers to elements by the same stable identifiers the model uses.
- **P5 digital twin** renders GRIDWISE's own types and result models, not pandapower's, and
  reads coordinates stored with the topology.

## Consequences

- The whole Python workspace stays on pandas 2.3 and numpy below 2.5 while pandapower
  requires it (decision 0001).
- The API image doubles in size (343 MB to 705 MB, after removing the scientific packages'
  own test suites; 825 MB with them). It carries the solver for the worker processes
  even though the API process never loads it. If that becomes a deployment cost, the worker
  gets its own image; the code boundary already allows it.
- Each worker process costs about 190 MB. On the 4 GB development VM the default is one.
- numba is not installed. pandapower runs without it and prints a notice on import; solve
  times above are without numba.

## P1.2 design decisions

Approved 2026-11-12 with the P1.2 plan.

| #   | Decision                                                                                                                                                                                             | Status          |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| D1  | A line or transformer with an open switch at one end stays energised from the other end (charging current, no-load power). The out-of-service-bus rule of decision 4 is unchanged and applies first. | done (P1.2a)    |
| D2  | Reactive limits of voltage-controlled generators are enforced by the solver; a limited unit is flagged in the result and no longer holds its set-point.                                              | done (P1.2a)    |
| D3  | Through the API, single elements can change operating state and name only (`in_service`, switch `closed`). Electrical parameters change by replacing the whole topology.                             | P1.2c           |
| D4  | Every stored grid passes engine validation; a grid is created together with its topology.                                                                                                            | P1.2c           |
| D5  | Optimistic concurrency: a grid `version`, `ETag`, and a required `If-Match` on writes.                                                                                                               | P1.2b and P1.2c |
| D6  | Buses carry optional schematic diagram coordinates in the database. They are not part of the electrical model or of the grid hash.                                                                   | P1.2b           |

Further decisions made while implementing P1.2a:

- **One `Generator` type with a control mode** (`constant_power`, `voltage_control`) rather
  than two types. A field that belongs to the other mode is an error, not ignored.
- **One voltage reference per bus.** A voltage-controlled generator may not share a bus with
  an external grid or with another voltage-controlled generator, even at the same
  set-point: how reactive power would be shared between them is not defined by the model.
  This is stricter than the plan, which only excluded differing set-points.
- **Generators do not energise an island.** Only an external grid provides a reference.
- **No invented plausibility bounds.** A transformer's rated voltages may differ from the
  bus voltages by any amount as long as HV exceeds LV.
- **The demonstration network is the CIGRE MV benchmark** with distributed generation, as
  literal data in the engine package. A test compares it with pandapower's copy, so its
  values are published ones and none is invented.
- **Hash schemas moved to version 2** (grid and result). No hash was stored anywhere yet.

## Out of scope for P1

Battery storage, unbalanced calculation, editing the electrical parameters of single
elements (D3), authentication, message brokers, forecasting and 3D rendering.
