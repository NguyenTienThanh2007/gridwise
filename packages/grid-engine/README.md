# gridwise-grid-engine

The GRIDWISE electrical domain engine. Pure Python: no HTTP, no database, no frontend.

```
model.py        Bus, Line, Load, ExternalGrid, GridModel (units in every field name)
validation.py   electrical and topological checks with stable error codes
topology.py     which buses are energised
solver.py       solver interface and options
engine.py       run_power_flow(): validate -> solve -> check -> typed result
results.py      result models
hashing.py      canonical input and result hashes
adapters/       the only code that imports pandapower
```

Model, equations, error codes and limits: `docs/domain/grid-engine.md`.

Self-check (solves a two-bus case and compares it with a closed-form solution):

```bash
make test-engine          # engine tests, then the self-check
```

Inside the API image: `python -m gridwise_grid_engine.selfcheck`.
