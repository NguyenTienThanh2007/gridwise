import json
from dataclasses import replace

import pytest
from grid_factories import three_bus_radial, with_line

from gridwise_grid_engine import PowerFlowSolver, run_power_flow
from gridwise_grid_engine.reference_grids import cigre_mv
from gridwise_grid_engine.result_documents import result_document_text
from gridwise_grid_engine.result_summaries import (
    NOT_CONVERGED,
    RESULT_SUMMARY_SCHEMA,
    ResultDocumentError,
    summarize_result_document,
)
from gridwise_grid_engine.scenarios import apply_scenario, demand_increase


def test_the_summary_of_the_benchmark(solver: PowerFlowSolver) -> None:
    result = run_power_flow(cigre_mv.cigre_mv_with_der(), solver)
    summary = summarize_result_document(result_document_text(result))
    voltages = {bus.bus_id: bus.voltage_pu for bus in result.buses if bus.voltage_pu is not None}
    loadings = {
        line.line_id: line.loading_percent
        for line in result.lines
        if line.loading_percent is not None
    }

    assert summary.schema == RESULT_SUMMARY_SCHEMA
    assert summary.converged is True
    assert summary.min_bus_voltage_pu is not None
    assert summary.max_bus_voltage_pu is not None
    assert summary.min_bus_voltage_pu.value == min(voltages.values())
    assert voltages[summary.min_bus_voltage_pu.key] == summary.min_bus_voltage_pu.value
    assert summary.max_bus_voltage_pu.value == max(voltages.values())
    assert summary.max_line_loading_percent is not None
    assert summary.max_line_loading_percent.value == max(loadings.values())
    assert summary.max_transformer_loading_percent is not None
    assert summary.totals is not None
    assert summary.totals == type(summary.totals)(**vars_of(result.totals))
    assert (summary.de_energised_buses, summary.de_energised_lines) == (0, 0)
    assert summary.unsupplied_bus_ids == ()


def vars_of(totals: object) -> dict[str, float]:
    from dataclasses import asdict

    return asdict(totals)  # type: ignore[call-overload,no-any-return]


def test_de_energised_elements_are_counted_and_not_extremes(solver: PowerFlowSolver) -> None:
    result = run_power_flow(with_line(three_bus_radial(), "bc", in_service=False), solver)
    summary = summarize_result_document(result_document_text(result))
    assert (summary.de_energised_buses, summary.de_energised_lines) == (1, 1)
    assert summary.unsupplied_bus_ids == ("c",)
    assert summary.min_bus_voltage_pu is not None
    assert summary.min_bus_voltage_pu.key != "c"  # no value is not a low value


def test_lines_over_their_rating_are_counted(solver: PowerFlowSolver) -> None:
    grid = with_line(three_bus_radial(), "ab", max_i_ka=0.05)  # carries about 0.09 kA
    summary = summarize_result_document(result_document_text(run_power_flow(grid, solver)))
    assert summary.lines_over_rating == 1
    assert summary.max_line_loading_percent is not None
    assert summary.max_line_loading_percent.key == "ab"
    assert summary.max_line_loading_percent.value > 100


def test_ties_are_broken_by_key(solver: PowerFlowSolver) -> None:
    grid = apply_scenario(cigre_mv.cigre_mv_with_der(), demand_increase(1.0))
    first = summarize_result_document(result_document_text(run_power_flow(grid, solver)))
    second = summarize_result_document(result_document_text(run_power_flow(replace(grid), solver)))
    assert first == second


def test_a_run_that_did_not_converge_has_no_values() -> None:
    assert NOT_CONVERGED.converged is False
    assert NOT_CONVERGED.totals is None
    assert NOT_CONVERGED.min_bus_voltage_pu is None
    assert NOT_CONVERGED.lines_over_rating is None


@pytest.mark.parametrize(
    "text",
    [
        "nope",
        "[]",
        json.dumps({"schema": "other"}),
        json.dumps({"schema": "gridwise.power-flow-result-document/1"}),
    ],
)
def test_anything_but_a_result_document_is_refused(text: str) -> None:
    with pytest.raises(ResultDocumentError):
        summarize_result_document(text)
