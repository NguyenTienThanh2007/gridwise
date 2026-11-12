"""Smoke test for a deployed environment: ``python -m gridwise_grid_engine.selfcheck``.

Solves a two-bus network and compares the result with constants obtained from the
closed-form solution of the two-bus power flow (derivation: docs/domain/grid-engine.md).
Exits non-zero if the installed solver stack does not reproduce them.
"""

import math
import platform
import sys

from gridwise_grid_engine.adapters.pandapower_adapter import PandapowerSolver
from gridwise_grid_engine.engine import run_power_flow
from gridwise_grid_engine.hashing import result_hash
from gridwise_grid_engine.model import Bus, ExternalGrid, GridModel, Line, Load

# 20 kV, slack at 1.0 pu, line R = 1.0 ohm, X = 0.5 ohm, load 4 MW + 1.5 MVAr.
EXPECTED_VOLTAGE_PU = 0.9879797221653659
EXPECTED_ANGLE_DEGREE = -0.07249110674251742
EXPECTED_LOSS_MW = 0.046741948814913614
EXPECTED_LOADING_PERCENT = 41.60749078520892
TOLERANCE = 1e-6


def reference_grid() -> GridModel:
    return GridModel(
        name="two-bus reference",
        frequency_hz=50.0,
        buses=(
            Bus(id="source", name="Source", nominal_voltage_kv=20.0),
            Bus(id="load", name="Load", nominal_voltage_kv=20.0),
        ),
        lines=(
            Line(
                id="line",
                name="Line",
                from_bus_id="source",
                to_bus_id="load",
                length_km=5.0,
                r_ohm_per_km=0.2,
                x_ohm_per_km=0.1,
                c_nf_per_km=0.0,
                max_i_ka=0.3,
            ),
        ),
        loads=(Load(id="demand", name="Demand", bus_id="load", p_mw=4.0, q_mvar=1.5),),
        external_grids=(ExternalGrid(id="slack", name="Slack", bus_id="source"),),
    )


def main() -> int:
    solver = PandapowerSolver()
    result = run_power_flow(reference_grid(), solver)
    print(f"python {platform.python_version()} on {platform.system()} {platform.machine()}")
    print(f"solver {solver.name} {solver.version}; converged={result.converged}")
    if not result.converged or result.totals is None:
        print("FAILED: the reference case did not converge")
        return 1

    load_bus = next(bus for bus in result.buses if bus.bus_id == "load")
    line = result.lines[0]
    checks = {
        "voltage_pu": (load_bus.voltage_pu, EXPECTED_VOLTAGE_PU),
        "voltage_angle_degree": (load_bus.voltage_angle_degree, EXPECTED_ANGLE_DEGREE),
        "active_losses_mw": (result.totals.active_losses_mw, EXPECTED_LOSS_MW),
        "loading_percent": (line.loading_percent, EXPECTED_LOADING_PERCENT),
    }
    failed = False
    for name, (actual, expected) in checks.items():
        ok = actual is not None and math.isclose(actual, expected, rel_tol=0.0, abs_tol=TOLERANCE)
        failed |= not ok
        print(f"{'ok    ' if ok else 'FAILED'} {name}: {actual!r} (expected {expected!r})")
    print(f"result hash {result_hash(result)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
