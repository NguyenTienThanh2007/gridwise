"""Canonical hashes for reproducibility.

``grid_hash`` identifies an input by its electrical content. Element order does not
matter, and neither does how a number was written: ``50`` and ``50.0`` are the same
frequency, ``-0.0`` and ``0.0`` the same reactive power.

``result_hash`` identifies a solution after normalisation: result values are rounded to
``RESULT_HASH_DECIMALS`` so that differences far below engineering relevance (and below the
solver's own tolerance) do not change it. The solver options are part of the identity and
are hashed exactly, never rounded. Solver name and version are excluded, so the same
physics gives the same hash across solver patch releases.

Neither function accepts NaN or infinity: hashing them raises ``ValueError``. A validated
grid and an engine-produced result never contain them.
"""

import hashlib
import json
from dataclasses import asdict
from typing import Any

from gridwise_grid_engine.model import ELEMENT_GROUPS, GridModel
from gridwise_grid_engine.results import PowerFlowResult

RESULT_HASH_DECIMALS = 6


def _digest(document: Any) -> str:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _by_id(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: str(item[key]))


def _canonical_number(value: Any) -> Any:
    """One representation per real number: ints become floats, -0.0 becomes 0.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return float(value) + 0.0


def _canonical_input(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical_input(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_input(item) for item in value]
    return _canonical_number(value)


def grid_hash(grid: GridModel) -> str:
    document = _canonical_input(asdict(grid))
    for group in ELEMENT_GROUPS:
        document[group] = _by_id(document[group], "id")
    return _digest({"schema": "gridwise.grid/2", "grid": document})


def _normalise(value: Any) -> Any:
    """Round result values. Never applied to solver options."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return round(value, RESULT_HASH_DECIMALS) + 0.0  # "+ 0.0" turns -0.0 into 0.0
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return value


def result_hash(result: PowerFlowResult) -> str:
    document = {
        "schema": "gridwise.power-flow-result/2",
        "grid_hash": result.grid_hash,
        "converged": result.converged,
        "failure_code": result.failure_code.value if result.failure_code else None,
        "buses": _by_id([asdict(item) for item in result.buses], "bus_id"),
        "lines": _by_id([asdict(item) for item in result.lines], "line_id"),
        "transformers": _by_id([asdict(item) for item in result.transformers], "transformer_id"),
        "generators": _by_id([asdict(item) for item in result.generators], "generator_id"),
        "external_grids": _by_id(
            [asdict(item) for item in result.external_grids], "external_grid_id"
        ),
        "totals": asdict(result.totals) if result.totals else None,
        "unsupplied_bus_ids": list(result.unsupplied_bus_ids),
    }
    return _digest(
        {
            "result": _normalise(document),
            "algorithm": result.algorithm,
            # Exact: a tolerance of 1e-8 and one of 1e-10 are different computations.
            "options": _canonical_input(asdict(result.options)),
        }
    )
