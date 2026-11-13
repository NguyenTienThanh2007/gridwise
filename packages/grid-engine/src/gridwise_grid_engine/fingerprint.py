"""Fingerprints of how a simulation is computed.

* ``configuration_hash``: the numerical configuration (algorithm and options), exact.
* ``engine_fingerprint``: the configuration plus the software that computed it: engine
  version, solver name and solver version.

Pure Python. The solver version is passed in by whoever ran the solver; nothing here
imports it.
"""

from dataclasses import asdict

from gridwise_grid_engine.engine import ALGORITHM
from gridwise_grid_engine.hashing import _canonical_input, canonical_json, sha256_hex
from gridwise_grid_engine.solver import PowerFlowOptions

CONFIGURATION_SCHEMA = "gridwise.power-flow-configuration/1"


def configuration_text(options: PowerFlowOptions, algorithm: str = ALGORITHM) -> str:
    return canonical_json(
        {
            "schema": CONFIGURATION_SCHEMA,
            "algorithm": algorithm,
            # Exact, like result_hash: 1e-8 and 1e-10 are different computations.
            "options": _canonical_input(asdict(options)),
        }
    )


def configuration_hash(options: PowerFlowOptions, algorithm: str = ALGORITHM) -> str:
    return sha256_hex(configuration_text(options, algorithm))


def engine_fingerprint(
    *,
    engine_version: str,
    solver_name: str,
    solver_version: str,
    options: PowerFlowOptions,
    algorithm: str = ALGORITHM,
) -> str:
    return sha256_hex(
        canonical_json(
            {
                "schema": "gridwise.engine-fingerprint/1",
                "engine_version": engine_version,
                "solver": {"name": solver_name, "version": solver_version},
                "configuration": configuration_hash(options, algorithm),
            }
        )
    )
