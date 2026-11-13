"""A power flow result as canonical text: what a simulation stores.

Exact values (not rounded, unlike ``result_hash``), sorted, schema
``gridwise.power-flow-result-document/1``. ``None`` stays ``null``: a de-energised element
has no value, never zero. Only converged results are documents; a run that did not
converge has no values to store.

Pure Python, no numerical library.
"""

from dataclasses import asdict
from typing import Any

from gridwise_grid_engine.hashing import _canonical_input, canonical_json
from gridwise_grid_engine.results import PowerFlowResult

RESULT_DOCUMENT_SCHEMA = "gridwise.power-flow-result-document/1"


def _by(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: str(item[key]))


def result_document_text(result: PowerFlowResult) -> str:
    if not result.converged:
        raise ValueError("only a converged result has values to store")
    document = {
        "schema": RESULT_DOCUMENT_SCHEMA,
        "grid_hash": result.grid_hash,
        "algorithm": result.algorithm,
        "options": asdict(result.options),
        "solver": {"name": result.solver_name, "version": result.solver_version},
        "buses": _by([asdict(item) for item in result.buses], "bus_id"),
        "lines": _by([asdict(item) for item in result.lines], "line_id"),
        "transformers": _by([asdict(item) for item in result.transformers], "transformer_id"),
        "generators": _by([asdict(item) for item in result.generators], "generator_id"),
        "external_grids": _by([asdict(item) for item in result.external_grids], "external_grid_id"),
        "totals": asdict(result.totals) if result.totals else None,
        "unsupplied_bus_ids": list(result.unsupplied_bus_ids),
    }
    return canonical_json(_canonical_input(document))
