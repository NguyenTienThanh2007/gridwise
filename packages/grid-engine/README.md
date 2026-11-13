# gridwise-grid-engine

The GRIDWISE electrical domain engine. Pure Python: no HTTP, no database, no frontend.

```
model.py        Bus, Line, Transformer, Load, Generator, ExternalGrid, Switch, GridModel
                (units in every field name)
validation.py   electrical and topological checks with stable error codes
topology.py     which buses, lines and transformers are energised, given the switches
solver.py       solver interface and options
engine.py       run_power_flow(): validate -> solve -> check -> typed result
results.py      result models
hashing.py      canonical input and result hashes
adapters/       the only code that imports pandapower
reference_grids/  published benchmark networks as plain data (synthetic, not real grids)
snapshots.py    a grid as canonical text whose hash is its grid_hash, and back
scenarios.py    deterministic modifications of a copy of a grid; five presets
fingerprint.py  hashes of the numerical configuration and of the engine that ran it
result_documents.py  a converged result as canonical text, as simulations store it
```

Model, equations, error codes and limits: `docs/domain/grid-engine.md`.

Self-check (solves a two-bus case and compares it with a closed-form solution):

```bash
make test-engine          # engine tests, then the self-check
```

Inside the API image: `python -m gridwise_grid_engine.selfcheck`.
