"""A compact summary of a stored power flow result, for lists and dashboards.

Computed from the canonical result document (result_documents.py), so it describes exactly
what was stored. It adds no limits or thresholds the engine does not model: it reports
extremes, and counts lines and transformers above 100 % of their own rating.

``None`` means "no value": a run that did not converge has a summary with no values at all,
and an extreme is ``None`` when no element of that kind is energised.

Pure Python, no numerical library.
"""

import json
from dataclasses import dataclass
from typing import Any

from gridwise_grid_engine.result_documents import RESULT_DOCUMENT_SCHEMA

RESULT_SUMMARY_SCHEMA = "gridwise.result-summary/1"


class ResultDocumentError(ValueError):
    """The text is not a result document this engine can read."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Extreme:
    key: str
    value: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultTotals:
    external_supply_mw: float
    external_supply_mvar: float
    generation_mw: float
    generation_mvar: float
    unavailable_generation_mw: float
    served_load_mw: float
    served_load_mvar: float
    unserved_load_mw: float
    unserved_load_mvar: float
    active_losses_mw: float
    reactive_losses_mvar: float


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultSummary:
    converged: bool
    totals: ResultTotals | None = None
    min_bus_voltage_pu: Extreme | None = None
    max_bus_voltage_pu: Extreme | None = None
    max_line_loading_percent: Extreme | None = None
    max_transformer_loading_percent: Extreme | None = None
    #: Energised lines and transformers loaded above 100 % of their own rating.
    lines_over_rating: int | None = None
    transformers_over_rating: int | None = None
    de_energised_buses: int | None = None
    de_energised_lines: int | None = None
    de_energised_transformers: int | None = None
    unsupplied_bus_ids: tuple[str, ...] | None = None
    schema: str = RESULT_SUMMARY_SCHEMA


NOT_CONVERGED = ResultSummary(converged=False)


def _extreme(items: list[dict[str, Any]], key: str, field: str, *, highest: bool) -> Extreme | None:
    values = [(item[field], item[key]) for item in items if item[field] is not None]
    if not values:
        return None
    # Ties are broken by key, so the summary is deterministic.
    value, element = (
        min(values, key=lambda pair: (-pair[0], pair[1]))
        if highest
        else min(values, key=lambda pair: (pair[0], pair[1]))
    )
    return Extreme(key=str(element), value=float(value))


def summarize_result_document(text: str) -> ResultSummary:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ResultDocumentError("the result is not JSON") from error
    if not isinstance(document, dict) or document.get("schema") != RESULT_DOCUMENT_SCHEMA:
        raise ResultDocumentError(f"the result is not a {RESULT_DOCUMENT_SCHEMA} document")
    try:
        buses, lines = document["buses"], document["lines"]
        transformers = document["transformers"]
        totals = document["totals"]
        return ResultSummary(
            converged=True,
            totals=ResultTotals(**totals) if totals is not None else None,
            min_bus_voltage_pu=_extreme(buses, "bus_id", "voltage_pu", highest=False),
            max_bus_voltage_pu=_extreme(buses, "bus_id", "voltage_pu", highest=True),
            max_line_loading_percent=_extreme(lines, "line_id", "loading_percent", highest=True),
            max_transformer_loading_percent=_extreme(
                transformers, "transformer_id", "loading_percent", highest=True
            ),
            lines_over_rating=sum(
                1
                for item in lines
                if item["loading_percent"] is not None and item["loading_percent"] > 100
            ),
            transformers_over_rating=sum(
                1
                for item in transformers
                if item["loading_percent"] is not None and item["loading_percent"] > 100
            ),
            de_energised_buses=sum(1 for item in buses if not item["energized"]),
            de_energised_lines=sum(1 for item in lines if not item["energized"]),
            de_energised_transformers=sum(1 for item in transformers if not item["energized"]),
            unsupplied_bus_ids=tuple(document["unsupplied_bus_ids"]),
        )
    except (KeyError, TypeError) as error:
        raise ResultDocumentError("the result document is incomplete") from error
