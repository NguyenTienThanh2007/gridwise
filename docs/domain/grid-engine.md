# Grid engine: model, equations and limits

`packages/grid-engine` computes the steady-state AC power flow of an electrical network.
This document states exactly what it models, the equations behind it, how it is verified
and what it does not do. It describes P1.1; later milestones extend it.

GRIDWISE is a simulation and decision-support tool. Nothing here measures or controls a
real network, and every number the engine produces is a calculation on the inputs it was
given.

## What is modelled

| Element        | Meaning                                            | Parameters                                                             |
| -------------- | -------------------------------------------------- | ---------------------------------------------------------------------- |
| `Bus`          | A node at one nominal voltage level                | `nominal_voltage_kv`                                                   |
| `Line`         | An overhead line or cable between two buses        | `length_km`, `r_ohm_per_km`, `x_ohm_per_km`, `c_nf_per_km`, `max_i_ka` |
| `Load`         | A constant-power (PQ) consumer                     | `p_mw`, `q_mvar`                                                       |
| `ExternalGrid` | The upstream network: the slack (reference) source | `voltage_pu`, `voltage_angle_degree`                                   |
| `GridModel`    | A whole network                                    | `frequency_hz` (50 or 60)                                              |

Every element has an `id`, a `name` and an `in_service` flag.

### Units and conventions

| Quantity         | Unit        | Convention                                         |
| ---------------- | ----------- | -------------------------------------------------- |
| Voltage          | kV          | Line-to-line RMS                                   |
| Voltage (result) | per unit    | Of the bus's nominal voltage                       |
| Angle            | degree      | Relative to the external grid's angle set-point    |
| Active power     | MW          | Three-phase total                                  |
| Reactive power   | MVAr        | Three-phase total; positive is inductive (lagging) |
| Current          | kA          | Line current, RMS                                  |
| Length           | km          |                                                    |
| Line parameters  | Ω/km, nF/km | Per phase, positive sequence                       |
| Frequency        | Hz          |                                                    |

Signs in results:

- **Bus** `p_mw`, `q_mvar`: net power withdrawn from the network at the bus. A bus that only
  feeds the network (the slack bus) is negative.
- **Line** `p_from_mw`, `p_to_mw` (and `q_…`): power flowing into the line at that end.
- **External grid** `p_mw`, `q_mvar`: power supplied to the network.

`None` in a result always means "no value exists" (the element is de-energised). It never
means zero.

## Assumptions

1. **Balanced three-phase system.** The network is represented by its positive-sequence
   single-phase equivalent. Unbalanced loads and single-phase connections are not modelled.
2. **Steady state.** One operating point per solve. No dynamics, transients or harmonics.
3. **Constant-power loads.** A load draws its `p_mw` and `q_mvar` regardless of voltage.
4. **Ideal slack.** The external grid holds its bus voltage exactly and supplies any power.
5. **Lumped lines.** Each line is a nominal π-equivalent; no temperature dependence, and
   shunt conductance is zero.

## Equations

### Line model

For a line of length _l_ at frequency _f_, per phase:

```
Z = (r + j·x) · l                       series impedance, Ω
Y = j · 2π · f · c · 10⁻⁹ · l           shunt admittance, S   (c in nF/km)
```

`Y/2` is connected at each end (nominal π-equivalent).

### Power flow

With bus voltages `V_i = |V_i| ∠ θ_i` and the bus admittance matrix `Y_bus = G + j·B` built
from the line models, the injected power at bus _i_ is

```
P_i = |V_i| · Σ_k |V_k| · (G_ik · cos θ_ik + B_ik · sin θ_ik)
Q_i = |V_i| · Σ_k |V_k| · (G_ik · sin θ_ik − B_ik · cos θ_ik)        θ_ik = θ_i − θ_k
```

The slack bus has `|V|` and `θ` fixed; every other bus has `P` and `Q` fixed by its loads.
The unknown voltages are found with the **Newton-Raphson** method, starting from a flat
profile (1.0 pu, 0°) on every run, until the largest bus power mismatch is below
`tolerance_mva` (default 1e-8 MVA) or `max_iterations` (default 10) is reached.

### Derived results

```
I_from = |S_from| / (√3 · |V_from|)                       kA
current_ka        = max(I_from, I_to)
loading_percent   = current_ka / max_i_ka · 100
active_loss_mw    = p_from_mw + p_to_mw
reactive_loss_mvar = q_from_mvar + q_to_mvar              negative when charging dominates
```

### Solver

The equations are solved by [pandapower](https://www.pandapower.org) 3.5.x (`runpp`,
algorithm `nr`). GRIDWISE does not implement its own numerical solver. pandapower is used
only inside `adapters/pandapower_adapter.py`; the rest of the engine is plain Python.

## What the engine guarantees

`run_power_flow(grid, solver)` performs, in order:

1. **Validation.** Every problem is reported at once with a code from the table below. An
   invalid grid is never passed to the solver.
2. **Energisation analysis.** A graph search finds the buses an in-service external grid
   can reach through in-service lines.
3. **Solve.** A new solver network is built from the model on every call.
4. **Checks on the solution**, independent of the solver:
   - every energised bus, line and source has finite values, and voltages are positive;
   - every de-energised element has none;
   - supply equals served load plus losses, for both active and reactive power, within
     `max(1e-6, 100 · tolerance_mva · energised buses)` MW/MVAr.

Outcomes:

| Situation                                  | Outcome                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------ |
| Converged                                  | `converged = True` with results and totals                                           |
| Did not converge                           | `converged = False`, `failure_code = power_flow_not_converged`, **no values at all** |
| Invalid input                              | `GridValidationError` with every issue                                               |
| Solver crashed                             | `SolverExecutionError` (`solver_failed`); the solver's message is not exposed        |
| Solution fails a check                     | `SolverExecutionError` (`inconsistent_solution`); nothing is returned                |
| Part of the network has no source (outage) | Solved; those buses and lines have `None`; their load is reported as unserved        |

Element states must be real booleans: `in_service` given as text or a number is rejected,
not interpreted.

An outage is a valid network state, not an error. Out-of-service elements and buses that
no source can reach are reported as de-energised.

**Taking a bus out of service takes every element attached to it out of service.** In
particular, an in-service line whose far bus is out of service is not left energised from
its live end. A solver would otherwise model it as an open-ended line drawing charging
power; the engine does not model open-ended lines, so it removes the line explicitly and
the result equals switching that line off.

## Error codes

Stable: a code is never renamed or reused. A test fails if this table and the code differ.

| Code                             | Raised when                                                                |
| -------------------------------- | -------------------------------------------------------------------------- |
| `invalid_identifier`             | An element `id` is empty or not a string                                   |
| `duplicate_element_id`           | Two elements of the same type share an `id`                                |
| `invalid_number`                 | A numeric field is not a finite real number (NaN, infinity, text, boolean) |
| `invalid_in_service_flag`        | `in_service` is not a real boolean (for example the text `"false"`)        |
| `invalid_frequency`              | `frequency_hz` is not 50 or 60                                             |
| `no_buses`                       | The grid has no bus                                                        |
| `missing_external_grid`          | No in-service external grid is connected to an in-service bus (no slack)   |
| `invalid_nominal_voltage`        | `nominal_voltage_kv` ≤ 0                                                   |
| `unknown_bus_reference`          | A line, load or external grid refers to a bus that does not exist          |
| `line_connects_bus_to_itself`    | A line's two ends are the same bus                                         |
| `line_voltage_mismatch`          | A line joins buses of different nominal voltage (that needs a transformer) |
| `invalid_line_length`            | `length_km` ≤ 0                                                            |
| `negative_line_resistance`       | `r_ohm_per_km` < 0                                                         |
| `negative_line_reactance`        | `x_ohm_per_km` < 0                                                         |
| `zero_line_impedance`            | `r_ohm_per_km` and `x_ohm_per_km` are both 0                               |
| `negative_line_capacitance`      | `c_nf_per_km` < 0                                                          |
| `invalid_line_thermal_limit`     | `max_i_ka` ≤ 0                                                             |
| `negative_load_active_power`     | A load's `p_mw` < 0 (generation is not a load)                             |
| `invalid_external_grid_voltage`  | `voltage_pu` ≤ 0                                                           |
| `multiple_external_grids_on_bus` | More than one in-service external grid on the same bus                     |
| `power_flow_not_converged`       | The Newton-Raphson iteration did not reach the tolerance                   |
| `solver_failed`                  | The solver raised an unexpected error                                      |
| `inconsistent_solution`          | The solver's answer failed a consistency check                             |

## Verification

| Test                     | What it establishes                                                                                                                                                                                                   | Tolerance                                            |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Two-bus closed form      | Voltage, angle, flows, losses, current and loading equal the algebraic solution of the two-bus equations (7 cases)                                                                                                    | 1e-9 pu, 1e-8°, 1e-8 MW/MVAr, 1e-9 kA, 1e-6 %        |
| Line charging at no load | The π-model capacitance, its unit and the frequency are applied correctly (50 and 60 Hz)                                                                                                                              | 1e-9 pu                                              |
| Determinism              | Identical inputs give identical results and hashes, across solver instances, element orderings and number spellings (`50` / `50.0`, `-0.0` / `0.0`); solver options are hashed exactly                                | exact on one machine; hash on values rounded to 1e-6 |
| Hash regression          | A recorded result hash is reproduced. It has run on macOS arm64 only; CI will show whether Linux x86-64 agrees. Separately, the self-check's hash was identical on macOS arm64, Linux arm64 and emulated Linux x86-64 | values rounded to 1e-6                               |
| Non-convergence          | A case with provably no solution returns no values, also directly after a successful solve on the same solver                                                                                                         | —                                                    |
| Outages                  | De-energised buses and lines have no values; lost load is reported as unserved                                                                                                                                        | balance 1e-6 MW                                      |

The two-bus solution used as the reference comes from algebra, not from a power flow
program. With `V₂` as angle reference, `V₁ = V₂ + (R + jX)(P − jQ)/V₂`, which gives

```
V₂⁴ + (2(PR + QX) − V₁²) · V₂² + (P² + Q²)(R² + X²) = 0
```

The larger root is the operating point. No real root exists once the discriminant is
negative, which is how the non-convergence test constructs a case with no solution.

Observed agreement between the engine and the closed form is about 1e-12; the tolerances
above are deliberately looser than that and tighter than any engineering use.

## Limits

These are not modelled. Results must not be read as if they were.

- **Transformers, generators, switches, storage, shunts.** Only the four elements above
  exist, so a model has a single voltage level per connected part, and its only source is
  the external grid. Transformers and generators arrive in later P1 milestones.
- **Unbalanced operation.** No per-phase results, no neutral currents, no single-phase loads.
- **Voltage-dependent loads.** Loads are constant power; real demand usually falls with
  voltage, so low-voltage results are pessimistic.
- **Limits are not enforced.** `loading_percent` above 100 and voltages far from 1.0 pu are
  reported as calculated. The engine does not flag violations yet and applies no voltage
  limits, because none are part of the model.
- **No plausibility bounds.** Any positive voltage, impedance or length is accepted. A
  physically absurd but well-formed input produces a well-formed, absurd result.
- **No time.** A solve has no timestamp and no duration; time series are sequences of
  independent solves, added with scenarios in P1.3.
- **Convergence is not existence.** "Did not converge" means Newton-Raphson found no
  solution from a flat start within the iteration limit. It usually means the network is
  overloaded beyond its transfer capability, but it is not a proof.
- **Line model accuracy.** The nominal π-equivalent is accurate for short and medium lines.
  Very long lines need the distributed-parameter model, which is not used.
- **Reference validation so far is two-bus.** Agreement with published multi-bus benchmark
  networks is planned for when transformers and generators exist.
- **Synthetic data only.** No real network data is included or supported by a data pipeline.
