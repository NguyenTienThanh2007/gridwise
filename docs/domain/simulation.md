# Simulation: jobs, snapshots and scenarios

What GRIDWISE stores when a power flow is requested, and the rules that keep a result
traceable to exactly what was computed. Design: decision 0010.

Everything here is simulation. No job, scenario or switch position is sent to any
equipment, and every grid in GRIDWISE is synthetic.

## Submitting

`SimulationService.submit(organisation, grid, scenario?, configuration?, expected version?,
idempotency key?)`, in one tenant transaction:

1. share-lock the grid; refuse if its version is not the expected one;
2. rebuild the grid from its rows; refuse if it does not match the stored hash;
3. apply the scenario to a copy; refuse if it names elements the grid does not have;
4. validate the copy with the engine; refuse if it is not a valid grid;
5. store the base and input snapshots (deduplicated) and the job, `queued`.

A refusal stores nothing. No power flow runs during submission.

## What a job records

| Group         | Columns                                                                                          |
| ------------- | ------------------------------------------------------------------------------------------------ |
| Source        | `source_grid_id` (cleared if the grid is deleted), `source_grid_version`, `source_topology_hash` |
| Input         | `base_snapshot_id`, `input_snapshot_id`                                                          |
| Scenario      | `scenario_id` (cleared if the scenario is deleted), `scenario_spec`, `scenario_spec_hash`        |
| Configuration | `configuration` (algorithm and options), `configuration_hash`, `requested_engine_version`        |
| Request       | `idempotency_key`, `request_fingerprint`                                                         |
| Lifecycle     | `status`, `outcome`, `attempt`, `max_attempts`, lease columns, `failure_code`, `failure_message` |
| Execution     | `executed_engine_version`, `solver_name`, `solver_version`, `engine_fingerprint`                 |
| Time          | `created_at`, `started_at`, `finished_at`, `cancelled_at`, `updated_at`                          |

Everything in the first five groups is frozen by the database once the job exists.

## Lifecycle

| From → to             | By                     | When                                                                             |
| --------------------- | ---------------------- | -------------------------------------------------------------------------------- |
| `queued → running`    | worker                 | it claims the job and takes a lease                                              |
| `running → running`   | worker                 | heartbeat: the lease is extended                                                 |
| `running → completed` | worker                 | the power flow finished; outcome `converged` or `not_converged`                  |
| `running → failed`    | worker or lease reaper | the computation could not be trusted, or the worker was lost on the last attempt |
| `running → queued`    | lease reaper           | the worker was lost and attempts remain; the attempt is recorded                 |
| `queued → cancelled`  | API                    | the owner cancels before it starts                                               |

`completed`, `failed` and `cancelled` never change again.

## Failure codes

| Code                    | Meaning                                              | Retried                               |
| ----------------------- | ---------------------------------------------------- | ------------------------------------- |
| `solver_failed`         | The solver stopped with an error                     | no                                    |
| `inconsistent_solution` | The solution failed the engine's consistency checks  | no                                    |
| `execution_timeout`     | The computation exceeded the time limit              | no                                    |
| `worker_lost`           | The worker stopped responding, on every attempt      | (after `max_attempts` lease expiries) |
| `snapshot_corrupt`      | The stored input did not match its hash              | no                                    |
| `invalid_input`         | The stored input is not a valid grid for this engine | no                                    |

The message stored with a code is the fixed text from `simulation/failures.py`. Exception
text is never stored or shown.

## Reproducing a result

`make reproduce` (`python -m gridwise_worker.reproduce --pending`) takes each completed job
not yet reproduced, verifies its input snapshot's hash, runs `run_power_flow` with the job's
configuration in the worker's solver process, and records the verdict the database derives
from the stored result (`match`, `mismatch`, `differs_after_engine_change`, `result_missing`,
`not_reproducible`, `snapshot_corrupt`, `reproduction_failed`). Scenario code is not
involved: the input snapshot already is the scenario's result. Design: decision 0012.

## Summaries

`ResultService.get` returns a converged job's stored result document, checked against its
hash, and its summary: totals, voltage extremes, highest line and transformer loading with
their keys, counts of elements above 100 % of their rating and of de-energised elements.
A job that did not converge has a summary with no values.

## Retention

Nothing is deleted automatically. `python -m gridwise_api.retention --finished-before
<time>` reports what would go; with `--apply` it deletes finished jobs older than that,
their results, attempts and reproductions, and the snapshots no other job uses. Grids and
scenarios are never touched.

## The worker

`python -m gridwise_worker` (Compose profile `worker`) solves queued jobs. It reaches the
database only through the five worker functions, and runs the solver in a child process it
can kill. Rules and defaults: decision 0011.

A converged job has one row in `sim.results`: the engine's full result as canonical text,
written in the same transaction as the job's completion. A job that did not converge has
none.

## Limits

- There is no per-tenant queue fairness yet.
- Cancelling a running job is not supported.
