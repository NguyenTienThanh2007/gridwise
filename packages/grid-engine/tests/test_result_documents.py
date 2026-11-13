import json
from dataclasses import replace

import pytest
from grid_factories import three_bus_radial, two_bus, with_line

from gridwise_grid_engine import PowerFlowSolver, run_power_flow
from gridwise_grid_engine.result_documents import RESULT_DOCUMENT_SCHEMA, result_document_text


def test_a_result_document_is_canonical_and_exact(solver: PowerFlowSolver) -> None:
    result = run_power_flow(two_bus(), solver)
    text = result_document_text(result)
    document = json.loads(text)
    assert json.dumps(document, sort_keys=True, separators=(",", ":")) == text
    assert document["schema"] == RESULT_DOCUMENT_SCHEMA
    assert document["grid_hash"] == result.grid_hash
    bus = next(item for item in document["buses"] if item["bus_id"] == "load")
    assert bus["voltage_pu"] == result.buses[1].voltage_pu  # exact, not rounded


def test_de_energised_elements_are_null_never_zero(solver: PowerFlowSolver) -> None:
    result = run_power_flow(with_line(three_bus_radial(), "bc", in_service=False), solver)
    document = json.loads(result_document_text(result))
    dead = next(item for item in document["buses"] if item["bus_id"] == "c")
    assert dead["energized"] is False
    assert dead["voltage_pu"] is None
    assert document["unsupplied_bus_ids"] == ["c"]


def test_the_same_input_gives_the_same_document(solver: PowerFlowSolver) -> None:
    """Exact values: identical for identical input. (Reordering the elements can change
    the last bits of a float; that is what the rounded result_hash is for.)"""
    grid = three_bus_radial()
    assert result_document_text(run_power_flow(grid, solver)) == result_document_text(
        run_power_flow(replace(grid), solver)
    )


def test_a_run_that_did_not_converge_has_no_document(solver: PowerFlowSolver) -> None:
    result = run_power_flow(two_bus(p_mw=84.0, q_mvar=31.5), solver)
    assert not result.converged
    with pytest.raises(ValueError, match="converged"):
        result_document_text(result)
