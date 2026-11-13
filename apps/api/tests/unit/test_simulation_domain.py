import itertools

import pytest

from gridwise_api.simulation.configuration import SimulationConfiguration
from gridwise_api.simulation.failures import FAILURE_MESSAGES, FailureCode, failure_message
from gridwise_api.simulation.states import (
    API_TRANSITIONS,
    TERMINAL_STATUSES,
    TRANSITIONS,
    IllegalTransitionError,
    JobStatus,
    is_legal,
    require_transition,
)
from gridwise_grid_engine import PowerFlowOptions

LEGAL = {
    ("queued", "running"),
    ("queued", "cancelled"),
    ("running", "running"),
    ("running", "completed"),
    ("running", "failed"),
    ("running", "queued"),
}


@pytest.mark.parametrize(("current", "target"), list(itertools.product(JobStatus, JobStatus)))
def test_every_pair_of_states(current: JobStatus, target: JobStatus) -> None:
    legal = (current.value, target.value) in LEGAL
    assert is_legal(current, target) is legal
    if legal:
        require_transition(current, target)
    else:
        with pytest.raises(IllegalTransitionError):
            require_transition(current, target)


def test_terminal_states_have_no_way_out() -> None:
    assert {status.value for status in TERMINAL_STATUSES} == {"completed", "failed", "cancelled"}
    assert not any(current in TERMINAL_STATUSES for current, _ in TRANSITIONS)


def test_nothing_leads_back_to_queued_except_a_lost_worker() -> None:
    assert [pair for pair in TRANSITIONS if pair[1] is JobStatus.QUEUED] == [
        (JobStatus.RUNNING, JobStatus.QUEUED)
    ]


def test_the_api_may_only_cancel_a_queued_job() -> None:
    assert {(JobStatus.QUEUED, JobStatus.CANCELLED)} == API_TRANSITIONS
    assert API_TRANSITIONS <= TRANSITIONS


def test_the_default_configuration_is_the_engines() -> None:
    configuration = SimulationConfiguration()
    assert configuration.options() == PowerFlowOptions()
    assert configuration.hash() == SimulationConfiguration().hash()
    assert SimulationConfiguration(max_iterations=20).hash() != configuration.hash()


@pytest.mark.parametrize(
    "values",
    [
        {"tolerance_mva": 0.0},
        {"tolerance_mva": 1.0},
        {"max_iterations": 0},
        {"max_iterations": 101},
    ],
)
def test_the_configuration_has_the_engines_bounds(values: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must be in"):
        SimulationConfiguration(**values)  # type: ignore[arg-type]


def test_every_failure_code_has_a_fixed_message() -> None:
    assert set(FAILURE_MESSAGES) == set(FailureCode)
    for code in FailureCode:
        message = failure_message(code)
        assert message.endswith(".")
        assert "{" not in message  # not a template that could take input
