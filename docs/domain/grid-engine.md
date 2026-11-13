# Grid engine: model, equations and limits

`packages/grid-engine` computes the steady-state AC power flow of an electrical network.
This document states exactly what it models, the equations behind it, how it is verified
and what it does not do. It describes P1.2a; later milestones extend it.

GRIDWISE is a simulation and decision-support tool. Nothing here measures or controls a
real network, and every number the engine produces is a calculation on the inputs it was
given.

## What is modelled

| Element        | Meaning                                                            | Parameters                                                             |
| -------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| `Bus`          | A node at one nominal voltage level                                | `nominal_voltage_kv`                                                   |
| `Line`         | An overhead line or cable between two buses                        | `length_km`, `r_ohm_per_km`, `x_ohm_per_km`, `c_nf_per_km`, `max_i_ka` |
| `Load`         | A constant-power (PQ) consumer                                     | `p_mw`, `q_mvar`                                                       |
| `ExternalGrid` | The upstream network: the slack (reference) source                 | `voltage_pu`, `voltage_angle_degree`                                   |
| `Transformer`  | A two-winding transformer between two voltage levels               | nameplate data, see [Transformer model](#transformer-model)            |
| `Generator`    | A generating unit in one of two control modes                      | `p_mw`, `control_mode`, see [Generators](#generators)                  |
| `Switch`       | An ideal switch at a line or transformer end, or between two buses | `bus_id`, `element_type`, `element_id`, `closed`, `kind`               |
| `GridModel`    | A whole network                                                    | `frequency_hz` (50 or 60)                                              |

Every element has an `id` and a `name`. Every element except a switch has an `in_service`
flag; a switch has a position, `closed`.

A switch in this model is a state of the simulated network. It is not a command, and
nothing in GRIDWISE sends it to any equipment.

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
- **Transformer** `p_hv_mw`, `p_lv_mw` (and `q_…`): power flowing into the transformer at
  that side.
- **External grid** and **generator** `p_mw`, `q_mvar`: power supplied to the network. For a
  generator, positive `q_mvar` is injection (over-excited).

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
6. **Ideal switches.** A closed switch has no impedance and no losses; two buses joined by
   a closed switch are one electrical node.
7. **Only an external grid energises a network.** Generators inject power into a network
   that an external grid keeps alive; they do not form an island of their own.

## Equations

### Line model

For a line of length _l_ at frequency _f_, per phase:

```
Z = (r + j·x) · l                       series impedance, Ω
Y = j · 2π · f · c · 10⁻⁹ · l           shunt admittance, S   (c in nF/km)
```

`Y/2` is connected at each end (nominal π-equivalent).

### Transformer model

A two-winding transformer is described by its nameplate data and represented by a T
equivalent circuit: half of the series impedance on each side of the magnetising branch,
followed by an ideal transformer. With rated power `S_r` and rated voltage `V_r` of the
side the impedance is referred to:

```
|Z_k| = short_circuit_voltage_percent   / 100 · V_r² / S_r      series impedance, Ω
R_k   = short_circuit_resistive_percent / 100 · V_r² / S_r
X_k   = √(|Z_k|² − R_k²)

P_0 = iron_losses_kw                                            no-load active power
S_0 = no_load_current_percent / 100 · S_r                       no-load apparent power
Q_0 = √(S_0² − P_0²)                                            magnetising reactive power
```

These follow from the definitions of the nameplate values: the short-circuit voltage is the
fraction of rated voltage that drives rated current through the short-circuited
transformer, and the no-load current and iron losses are what it draws with the other side
open. `S_0 ≥ P_0` is therefore required, and checked.

The voltage ratio is that of the rated voltages, changed by the tap changer:

```
tap on the HV side:   V_hv / V_lv = V_r,hv · (1 + (position − neutral) · step_percent/100) / V_r,lv
tap on the LV side:   V_hv / V_lv = V_r,hv / (V_r,lv · (1 + (position − neutral) · step_percent/100))
```

Rated voltages may differ from the nominal voltages of the buses; the ratio is then
off-nominal even at the neutral tap. `phase_shift_degree` turns the low-voltage angle
against the high-voltage angle by that amount.

`loading_percent` is the larger of the two winding currents as a percentage of that
winding's rated current, `S_r / (√3 · V_r)`.

The exact circuit, including how the ratio and the phase shift enter the admittance matrix,
is pandapower's documented two-winding transformer model
([pandapower documentation, "Transformer"](https://pandapower.readthedocs.io/en/latest/elements/trafo.html)),
used with `trafo_model="t"`. The relations above are the ones the tests verify
independently.

### Generators

| `control_mode`    | Given                         | Solved                | Bus type |
| ----------------- | ----------------------------- | --------------------- | -------- |
| `constant_power`  | `p_mw`, `q_mvar`              | voltage               | PQ       |
| `voltage_control` | `p_mw`, `voltage_setpoint_pu` | reactive power, angle | PV       |

A voltage-controlled unit may have reactive limits (`min_q_mvar`, `max_q_mvar`). If holding
the set-point would need more than a limit, the unit stays at the limit and behaves as a
constant-power unit there; the bus voltage is then a result, not the set-point, and the
result says so (`reactive_limit_reached`).

### Switches and energisation

Applied in this order, by a graph search that does not involve the solver:

1. Taking a bus out of service takes every element attached to it out of service.
2. An open switch at one end of a line or transformer detaches that end only. The element
   stays energised from its other end: an open-ended line draws its charging current, an
   open-ended transformer its no-load power.
3. Power passes through a line or transformer only if both ends are attached, and between
   two buses joined by a switch only if it is closed.
4. A bus is energised if an in-service external grid can reach it this way.

### Power flow

With bus voltages `V_i = |V_i| ∠ θ_i` and the bus admittance matrix `Y_bus = G + j·B` built
from the line models, the injected power at bus _i_ is

```
P_i = |V_i| · Σ_k |V_k| · (G_ik · cos θ_ik + B_ik · sin θ_ik)
Q_i = |V_i| · Σ_k |V_k| · (G_ik · sin θ_ik − B_ik · cos θ_ik)        θ_ik = θ_i − θ_k
```

The slack bus has `|V|` and `θ` fixed. A bus with a voltage-controlled generator has `P` and
`|V|` fixed. Every other bus has `P` and `Q` fixed by its loads and constant-power
generators. The unknown voltages are found with the **Newton-Raphson** method, starting from a flat
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

Transformer losses are formed the same way from the HV and LV side powers.

### Solver

The equations are solved by [pandapower](https://www.pandapower.org) 3.5.x (`runpp`,
algorithm `nr`). GRIDWISE does not implement its own numerical solver. pandapower is used
only inside `adapters/pandapower_adapter.py`; the rest of the engine is plain Python.

## What the engine guarantees

`run_power_flow(grid, solver)` performs, in order:

1. **Validation.** Every problem is reported at once with a code from the table below. An
   invalid grid is never passed to the solver.
2. **Energisation analysis.** A graph search finds the buses, lines and transformers an
   in-service external grid can reach (see [Switches and energisation](#switches-and-energisation)).
3. **Solve.** A new solver network is built from the model on every call.
4. **Checks on the solution**, independent of the solver:
   - every energised bus, line, transformer, generator and source has finite values, and
     voltages are positive;
   - every de-energised element has none;
   - supply (external grids and generators) equals served load plus line and transformer
     losses, for both active and reactive power, within
     `max(1e-6, 100 · tolerance_mva · energised nodes)` MW/MVAr;
   - every generator delivers its active power set-point, and a constant-power one its
     reactive power;
   - a voltage-controlled generator either holds its set-point (within 1e-6 pu) with
     reactive power inside its limits, or sits at a limit (within 1e-6 MVAr). Anything
     else is rejected.

Outcomes:

| Situation                                  | Outcome                                                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Converged                                  | `converged = True` with results and totals                                                              |
| Did not converge                           | `converged = False`, `failure_code = power_flow_not_converged`, **no values at all**                    |
| Invalid input                              | `GridValidationError` with every issue                                                                  |
| Solver crashed                             | `SolverExecutionError` (`solver_failed`); the solver's message is not exposed                           |
| Solution fails a check                     | `SolverExecutionError` (`inconsistent_solution`); nothing is returned                                   |
| Part of the network has no source (outage) | Solved; those elements have `None`; their load is reported as unserved, their generation as unavailable |

Element states must be real booleans: `in_service` or `closed` given as text or a number is
rejected, not interpreted.

An outage is a valid network state, not an error. Out-of-service elements and buses that
no source can reach are reported as de-energised.

**Taking a bus out of service takes every element attached to it out of service.** An
in-service line whose far bus is out of service is removed entirely; the result equals
switching that line off.

**An open switch is different: it detaches one end only.** A line with an open switch at
one end stays energised from the other and draws its charging current; a transformer draws
its no-load power. This is what happens physically at a normally-open point, and it is how
the result reports it. (P1.1 had no switches and stated that open-ended lines were not
modelled. That statement no longer holds for switches; it still holds for out-of-service
buses.)

## Error codes

Stable: a code is never renamed or reused. A test fails if this table and the code differ.

| Code                                        | Raised when                                                                                                 |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `invalid_identifier`                        | An element `id` is empty or not a string                                                                    |
| `duplicate_element_id`                      | Two elements of the same type share an `id`                                                                 |
| `invalid_number`                            | A numeric field is not a finite real number (NaN, infinity, text, boolean)                                  |
| `invalid_in_service_flag`                   | `in_service` is not a real boolean (for example the text `"false"`)                                         |
| `invalid_frequency`                         | `frequency_hz` is not 50 or 60                                                                              |
| `no_buses`                                  | The grid has no bus                                                                                         |
| `missing_external_grid`                     | No in-service external grid is connected to an in-service bus (no slack)                                    |
| `invalid_nominal_voltage`                   | `nominal_voltage_kv` ≤ 0                                                                                    |
| `unknown_bus_reference`                     | A line, load or external grid refers to a bus that does not exist                                           |
| `line_connects_bus_to_itself`               | A line's two ends are the same bus                                                                          |
| `line_voltage_mismatch`                     | A line joins buses of different nominal voltage (that needs a transformer)                                  |
| `invalid_line_length`                       | `length_km` ≤ 0                                                                                             |
| `negative_line_resistance`                  | `r_ohm_per_km` < 0                                                                                          |
| `negative_line_reactance`                   | `x_ohm_per_km` < 0                                                                                          |
| `zero_line_impedance`                       | `r_ohm_per_km` and `x_ohm_per_km` are both 0                                                                |
| `negative_line_capacitance`                 | `c_nf_per_km` < 0                                                                                           |
| `invalid_line_thermal_limit`                | `max_i_ka` ≤ 0                                                                                              |
| `negative_load_active_power`                | A load's `p_mw` < 0 (generation is not a load)                                                              |
| `invalid_external_grid_voltage`             | `voltage_pu` ≤ 0                                                                                            |
| `multiple_external_grids_on_bus`            | More than one in-service external grid on the same bus                                                      |
| `transformer_connects_bus_to_itself`        | A transformer's two sides are the same bus                                                                  |
| `transformer_voltage_mismatch`              | The bus at `hv_bus_id` does not have a higher nominal voltage than the bus at `lv_bus_id`                   |
| `invalid_transformer_rated_power`           | `rated_power_mva` ≤ 0                                                                                       |
| `invalid_transformer_rated_voltage`         | `rated_voltage_lv_kv` ≤ 0, or `rated_voltage_hv_kv` ≤ `rated_voltage_lv_kv`                                 |
| `invalid_transformer_short_circuit_voltage` | `short_circuit_voltage_percent` ≤ 0, or the resistive part is negative or larger than the total             |
| `negative_transformer_iron_losses`          | `iron_losses_kw` < 0                                                                                        |
| `invalid_transformer_no_load_current`       | `no_load_current_percent` < 0, or smaller than the iron losses alone require                                |
| `invalid_tap_changer`                       | Side not `hv`/`lv`, a position that is not an integer or outside its range, or `step_percent` ≤ 0           |
| `negative_generator_active_power`           | A generator's `p_mw` < 0 (consumption is a load)                                                            |
| `invalid_generator_control_mode`            | `control_mode` is not `constant_power` or `voltage_control`                                                 |
| `invalid_generator_parameters`              | A field required by the control mode is missing, or a field of the other mode is given                      |
| `invalid_generator_voltage_setpoint`        | `voltage_setpoint_pu` ≤ 0                                                                                   |
| `invalid_generator_reactive_limits`         | Only one of `min_q_mvar` / `max_q_mvar` is given, or min > max                                              |
| `invalid_generator_rated_power`             | `rated_power_mva` ≤ 0                                                                                       |
| `generator_exceeds_rated_power`             | The set-point (√(p² + q²), or p alone under voltage control) exceeds `rated_power_mva`                      |
| `multiple_voltage_controllers_on_bus`       | A voltage-controlled generator shares its bus with an external grid or another voltage-controlled generator |
| `invalid_switch_state`                      | `closed` is not a real boolean                                                                              |
| `invalid_switch_element_type`               | `element_type` is not `line`, `transformer` or `bus`                                                        |
| `invalid_switch_kind`                       | `kind` is not one of the four known kinds                                                                   |
| `unknown_switch_target`                     | `element_id` refers to no element of the stated type                                                        |
| `switch_not_at_element_terminal`            | `bus_id` is not one of the ends of the line or transformer it switches                                      |
| `switch_connects_bus_to_itself`             | A bus-to-bus switch names the same bus twice                                                                |
| `switch_voltage_mismatch`                   | A bus-to-bus switch joins buses of different nominal voltage                                                |
| `duplicate_switch`                          | Two switches at the same end of the same element, or between the same pair of buses                         |
| `power_flow_not_converged`                  | The Newton-Raphson iteration did not reach the tolerance                                                    |
| `solver_failed`                             | The solver raised an unexpected error                                                                       |
| `inconsistent_solution`                     | The solver's answer failed a consistency check                                                              |

## Snapshots

A snapshot is a grid as canonical text (`snapshots.snapshot_text`): the exact document that
`grid_hash` hashes, schema `gridwise.grid/2`. So `sha256(text) == grid_hash(grid)`, and a
reader can check a snapshot without trusting where it came from. `grid_from_snapshot`
refuses text that does not match its expected hash, is not this schema, or is not in
canonical form. Simulations store their input as snapshots and never change them.

Diagram positions are not part of a snapshot: they are not electrical.

## Scenarios

A scenario (`scenarios.py`, document schema `gridwise.scenario/1`) is an ordered list of
modifications applied to a copy of a grid before it is simulated. The stored grid is never
changed. The same scenario on the same grid always gives the same model.

| Modification       | Effect                                                                                                                                          |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `scale_loads`      | Multiply `p_mw` and `q_mvar` of all loads, or of `keys`. `0 < factor ≤ 100`                                                                     |
| `scale_generation` | Multiply `p_mw` of all generators, or of `keys`, optionally of one `control_mode`; constant-power units also scale `q_mvar`. `0 ≤ factor ≤ 100` |
| `set_in_service`   | Take one bus, line, transformer, load, generator or external grid in or out of service                                                          |
| `set_switch`       | Set one switch's position in the simulated copy                                                                                                 |

Every key a scenario names must exist in the grid; otherwise nothing is applied and every
missing key is reported. A scenario may produce a grid the engine refuses (for example
scaling a unit beyond its rating, or taking out the only source): the result is validated
like any other grid.

Five presets cover the roadmap's study cases: `normal_operation`, `demand_increase` (loads
× 1.2), `transformer_overload` (loads × 1.6), `feeder_outage` (one line out of service) and
`renewable_generation` (constant-power units at their set-point, loads × 0.5). The factors
are illustrative study assumptions, not measured or forecast values.

Setting a switch in a scenario changes the simulated copy only. Nothing reaches equipment.

## Scenario error codes

Stable, like the grid error codes. A test fails if this table and the code differ.

| Code                            | Raised when                                                                |
| ------------------------------- | -------------------------------------------------------------------------- |
| `invalid_scenario_document`     | Not a `gridwise.scenario/1` document, or a modification has unknown fields |
| `unknown_modification`          | A modification's `type` is not one of the four                             |
| `too_many_modifications`        | More than 200 modifications                                                |
| `invalid_scale_factor`          | A factor is not a finite number in its range                               |
| `invalid_scenario_element_type` | `set_in_service` names an element type it cannot change                    |
| `invalid_scenario_key`          | A key is missing or blank, or `keys` is not a non-empty list of keys       |
| `invalid_scenario_flag`         | `in_service` or `closed` is not a real boolean                             |
| `invalid_scenario_control_mode` | `control_mode` is not `constant_power` or `voltage_control`                |
| `scenario_key_not_found`        | The grid has no element with a key the scenario names                      |

## Fingerprints

`fingerprint.configuration_hash` identifies the numerical configuration (algorithm and
options, exactly). `engine_fingerprint` adds the engine version and the solver's name and
version. The engine version changes whenever a recorded regression hash changes; a test
ties the two together.

## Verification

| Test                            | What it establishes                                                                                                                                                                                                                                                         | Tolerance                                                            |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Two-bus closed form             | Voltage, angle, flows, losses, current and loading equal the algebraic solution of the two-bus equations (7 cases)                                                                                                                                                          | 1e-9 pu, 1e-8°, 1e-8 MW/MVAr, 1e-9 kA, 1e-6 %                        |
| Line charging at no load        | The π-model capacitance, its unit and the frequency are applied correctly (50 and 60 Hz)                                                                                                                                                                                    | 1e-9 pu                                                              |
| Determinism                     | Identical inputs give identical results and hashes, across solver instances, element orderings and number spellings (`50` / `50.0`, `-0.0` / `0.0`); solver options are hashed exactly                                                                                      | exact on one machine; hash on values rounded to 1e-6                 |
| Hash regression                 | Recorded result hashes (two-bus, and the CIGRE MV benchmark) are reproduced. The P1.1 two-bus hash was reproduced on Linux x86-64 in CI. Both values were regenerated in P1.2a on macOS arm64 because the result document changed; CI will show whether Linux x86-64 agrees | values rounded to 1e-6                                               |
| Non-convergence                 | A case with provably no solution returns no values, also directly after a successful solve on the same solver                                                                                                                                                               | —                                                                    |
| Outages                         | De-energised buses and lines have no values; lost load is reported as unserved                                                                                                                                                                                              | balance 1e-6 MW                                                      |
| Transformer as series impedance | With no magnetising branch, voltage, angle, losses and both winding currents equal the two-bus closed form with `Z_k` as above (4 cases)                                                                                                                                    | 1e-9 pu, 1e-8°, 1e-8 MW/MVAr, 1e-9 kA                                |
| Transformer ratio               | No-load voltage for taps on either side, 5 positions each, a non-zero neutral position, and rated voltages that differ from the bus voltages                                                                                                                                | 1e-9 pu                                                              |
| Transformer no-load power       | An unloaded transformer draws its iron losses and magnetising reactive power                                                                                                                                                                                                | 0.1 % (half the series impedance lies before the magnetising branch) |
| Constant-power generator        | Two-bus closed form with the net demand (4 cases, including export)                                                                                                                                                                                                         | 1e-9 pu, 1e-8°, 1e-8 MW                                              |
| Voltage-controlled generator    | Set-point held; angle and reactive power equal the two-bus closed form for a fixed receiving voltage (5 cases)                                                                                                                                                              | 1e-9 pu, 1e-8°, 1e-7 MVAr                                            |
| Reactive limits                 | At a limit the unit equals a constant-power unit (closed form), in both directions; wide limits change nothing                                                                                                                                                              | 1e-9 pu, 1e-7 MVAr                                                   |
| Switch equivalences             | A line open at its far end equals a line to an unloaded bus; open at its supply end equals a line out of service; a closed bus coupler equals one bus; an open-ended transformer draws no-load power only                                                                   | 1e-12, or the solver tolerance 1e-8 MVA at an open end               |
| Power flow equations, 9 buses   | For `case9` (three sources, meshed), the engine's voltages are put back into the equations above in plain complex arithmetic; the power at every bus matches loads and sources. No solver or matrix library is involved                                                     | 1e-6 MVA per bus                                                     |
| Benchmark data                  | The shipped CIGRE MV network equals pandapower's copy element by element                                                                                                                                                                                                    | exact                                                                |
| Benchmark mapping               | CIGRE MV and `case9`, solved through the GRIDWISE model, equal pandapower solving its own copies. Same solver on both sides: this checks the model mapping, not the solver                                                                                                  | 1e-9                                                                 |
| Solution checks                 | A correct solution with one fault injected (wrong transformer flow, generator off its set-point, limits or switches ignored) is rejected, 14 cases                                                                                                                          | —                                                                    |

The two-bus solution used as the reference comes from algebra, not from a power flow
program. With `V₂` as angle reference, `V₁ = V₂ + (R + jX)(P − jQ)/V₂`, which gives

```
V₂⁴ + (2(PR + QX) − V₁²) · V₂² + (P² + Q²)(R² + X²) = 0
```

The larger root is the operating point. No real root exists once the discriminant is
negative, which is how the non-convergence test constructs a case with no solution.

For a voltage-controlled generator at bus 2 the receiving voltage `V₂` is given instead of
`Q`. With `Z = |Z|∠β` and `δ` the angle by which bus 2 lags bus 1, the power arriving at
bus 2 is

```
P_r = V₁V₂/|Z| · cos(β − δ) − V₂²/|Z| · cos β
Q_r = V₁V₂/|Z| · sin(β − δ) − V₂²/|Z| · sin β
```

`P_r` is known (load minus generation), which gives `δ`; `Q_r` then gives the reactive
power the generator supplies.

### Reference networks

| Network                                        | Source                                                                                                                                                            | Used for                                                                              |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| CIGRE MV benchmark with distributed generation | CIGRE Task Force C6.04.02, "Benchmark Systems for Network Integration of Renewable and Distributed Energy Resources", 2014; values as distributed with pandapower | Shipped in `reference_grids/cigre_mv.py`; the demonstration network; mapping tests    |
| `case9`                                        | Anderson and Fouad, "Power System Control and Stability"; data as distributed with pandapower (from PYPOWER)                                                      | Read from pandapower in tests only; voltage-controlled generators on a meshed network |

Both are synthetic test networks. Neither describes a real grid, and nothing in them is a
measurement.

What was **not** done: comparing `case9` with a printed table of published results. No
citable table could be retrieved while this was written, so no published numbers are
quoted. The equation check above replaces it and is independent of any solver.

Observed agreement between the engine and the closed form is about 1e-12; the tolerances
above are deliberately looser than that and tighter than any engineering use.

## Limits

These are not modelled. Results must not be read as if they were.

- **Storage, shunts, three-winding transformers, phase-shifting taps, parallel units.**
  Only the seven elements above exist.
- **Islanded operation.** A part of the network without an external grid is de-energised
  even if it contains generation. Its generation is reported as unavailable.
- **Generator capability.** Reactive limits are two fixed numbers, not a capability curve.
  Active power limits are not modelled: `p_mw` is taken as given.
- **Rated voltage plausibility.** A transformer's rated voltages may differ from the bus
  voltages by any amount, as long as HV exceeds LV. An implausible ratio is not rejected.
- **Switch ratings.** Switches are ideal and have no current rating; `kind` is descriptive.
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
- **Multi-bus validation is partly solver-dependent.** Lines and generators are verified on
  nine buses without a solver. Transformers and switches are verified on two to five buses
  by closed forms and equivalences; on the 15-bus benchmark they are compared with
  pandapower itself.
- **Synthetic data only.** No real network data is included or supported by a data pipeline.
