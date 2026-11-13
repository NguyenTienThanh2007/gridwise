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
| `queued → running`    | worker (P1.3b)         | it claims the job and takes a lease                                              |
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

Take the job's input snapshot, verify its hash, and run `run_power_flow` with the job's
configuration. The `result_hash` must equal the stored one (P1.3c). Scenario code is not
involved: the input snapshot already is the scenario's result.

## Limits

- Nothing runs queued jobs until the worker exists (P1.3b).
- Snapshots are kept indefinitely; there is no retention rule yet.
- There is no per-tenant queue fairness yet.
- Cancelling a running job is not supported.
