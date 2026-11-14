"""The scenario and simulation API's schemas, representations and documentation, without a
database."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from gridwise_api.api.errors import ApiError
from gridwise_api.api.routes.simulations import _detail, _idempotency_key, _job
from gridwise_api.api.schemas.simulations import ScenarioCreate, SubmissionRequest
from gridwise_api.repositories.simulations import AttemptRecord, JobRecord
from gridwise_api.services.simulations import JobDetails, JobView
from gridwise_api.simulation.configuration import SimulationConfiguration
from gridwise_grid_engine.scenarios import demand_increase, scenario_text

ORGANIZATION = uuid.UUID("0a0a0a0a-0000-4000-8000-00000000000a")
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)

# --- requests -------------------------------------------------------------------------------


def test_a_scenario_request_becomes_an_engine_document() -> None:
    body = ScenarioCreate.model_validate_json(
        json.dumps(
            {
                "name": "Peak",
                "modifications": [
                    {"type": "scale_loads", "factor": 1.2},
                    {"type": "scale_loads", "factor": 2, "keys": ["load-1"]},
                    {"type": "scale_generation", "factor": 0, "control_mode": "constant_power"},
                    {
                        "type": "set_in_service",
                        "element_type": "line",
                        "key": "l1",
                        "in_service": False,
                    },
                    {"type": "set_switch", "key": "s1", "closed": True},
                ],
            }
        )
    )
    assert body.document() == {
        "schema": "gridwise.scenario/1",
        "modifications": [
            {"type": "scale_loads", "factor": 1.2},
            {"type": "scale_loads", "factor": 2.0, "keys": ["load-1"]},
            {"type": "scale_generation", "factor": 0.0, "control_mode": "constant_power"},
            {"type": "set_in_service", "element_type": "line", "key": "l1", "in_service": False},
            {"type": "set_switch", "key": "s1", "closed": True},
        ],
    }


@pytest.mark.parametrize(
    "modification",
    [
        {"type": "open_breaker", "key": "s1"},  # not a modification type
        {"type": "set_switch", "key": "s1", "closed": "true"},  # text is not a boolean
        {"type": "set_switch", "key": "s1", "closed": True, "extra": 1},
        {"type": "scale_loads", "factor": "1.2"},
        {"type": "scale_loads", "factor": 1.2, "keys": []},
        {"type": "scale_generation", "factor": 1, "control_mode": "droop"},
        {"type": "set_in_service", "element_type": "switch", "key": "s1", "in_service": False},
        {"type": "set_in_service", "element_type": "line", "key": "bad key", "in_service": True},
    ],
)
def test_invalid_modifications_are_refused(modification: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate_json(
            json.dumps({"name": "x", "modifications": [modification]})
        )


def test_non_finite_numbers_and_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate_json(
            '{"name": "x", "modifications": [{"type": "scale_loads", "factor": NaN}]}'
        )
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate_json('{"name": "x", "modifications": [], "owner": "me"}')
    with pytest.raises(ValidationError):
        ScenarioCreate.model_validate_json('{"name": "  ", "modifications": []}')


def test_a_submission_takes_a_uuid_string_and_engine_bounded_options() -> None:
    scenario = uuid.uuid4()
    body = SubmissionRequest.model_validate(
        {"scenario_id": str(scenario), "configuration": {"max_iterations": 20}}
    )
    assert body.scenario_id == scenario
    assert body.configuration is not None
    assert body.configuration.configuration() == SimulationConfiguration(max_iterations=20)
    assert SubmissionRequest.model_validate({}).configuration is None


@pytest.mark.parametrize(
    "body",
    [
        {"scenario_id": "not-a-uuid"},
        {"configuration": {"tolerance_mva": 1.0}},
        {"configuration": {"tolerance_mva": 0}},
        {"configuration": {"max_iterations": 0}},
        {"configuration": {"max_iterations": 101}},
        {"configuration": {"max_iterations": 1.5}},
        {"configuration": {"max_iterations": "10"}},
        {"configuration": {"algorithm": "gauss_seidel"}},
        {"grid_version": 3},
    ],
)
def test_invalid_submissions_are_refused(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SubmissionRequest.model_validate(body)


@pytest.mark.parametrize("key", ["a", "run-2026-11-14", "!~" * 100])
def test_idempotency_keys_follow_the_databases_rule(key: str) -> None:
    assert _idempotency_key(key) == key
    assert _idempotency_key(None) is None


@pytest.mark.parametrize("key", ["", "with space", "x" * 201, "é", "tab\there"])
def test_malformed_idempotency_keys_are_refused(key: str) -> None:
    with pytest.raises(ApiError) as raised:
        _idempotency_key(key)
    assert (raised.value.status_code, raised.value.code) == (400, "invalid_idempotency_key")


# --- representations ------------------------------------------------------------------------

#: Tenancy and infrastructure detail that no response may contain.
FORBIDDEN_FIELDS = {
    "organization_id",
    "lease_token",
    "lease_expires_at",
    "worker_id",
    "heartbeat_at",
    "request_fingerprint",
    "idempotency_key",
    "base_snapshot_id",
    "input_snapshot_id",
}


def _record() -> JobRecord:
    return JobRecord(
        id=uuid.uuid4(),
        organization_id=ORGANIZATION,
        source_grid_id=uuid.uuid4(),
        source_grid_version=3,
        source_topology_hash="a" * 64,
        base_snapshot_id=uuid.uuid4(),
        input_snapshot_id=uuid.uuid4(),
        scenario_id=None,
        scenario_spec=scenario_text(demand_increase(1.2)),
        scenario_spec_hash="b" * 64,
        configuration=SimulationConfiguration().text(),
        configuration_hash=SimulationConfiguration().hash(),
        requested_engine_version="0.3.0",
        idempotency_key="secret-key",
        request_fingerprint="c" * 64,
        max_attempts=3,
        status="failed",
        outcome=None,
        attempt=1,
        failure_code="execution_timeout",
        failure_message="The computation did not finish within the time limit.",
        executed_engine_version=None,
        solver_name=None,
        solver_version=None,
        engine_fingerprint=None,
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        cancelled_at=None,
        updated_at=NOW,
    )


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def test_job_representations_hold_no_tenancy_or_infrastructure_detail() -> None:
    record = _record()
    details = JobDetails(
        job=record,
        attempts=[
            AttemptRecord(
                attempt=1,
                worker_id="host-1:4242",
                started_at=NOW,
                ended_at=NOW,
                ended_by="failed",
            )
        ],
        source_status="changed",
        input_hash="d" * 64,
    )
    for response in (
        _detail(details),
        _job(JobView(job=record, source_status="changed", input_hash="d" * 64)),
    ):
        body = response.model_dump(mode="json")
        assert not _keys(body) & FORBIDDEN_FIELDS
        text = json.dumps(body)
        for secret in (str(ORGANIZATION), "secret-key", "host-1:4242", "c" * 64):
            assert secret not in text
        assert body["source"]["status"] == "changed"
        assert body["input_snapshot_hash"] == "d" * 64
        assert body["configuration"]["max_iterations"] == 10
        assert isinstance(body["configuration"]["max_iterations"], int)
        assert body["failure"] == {
            "code": "execution_timeout",
            "message": "The computation did not finish within the time limit.",
        }
        assert body["scenario"]["specification"]["schema"] == "gridwise.scenario/1"
        assert body["links"]["result"] == f"/api/v1/simulations/{record.id}/result"


# --- documentation --------------------------------------------------------------------------


async def test_every_operation_documents_its_errors_and_schemas(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    paths = schema["paths"]
    for path, item in paths.items():
        if not path.startswith(("/api/v1/scenarios", "/api/v1/simulations")) and not (
            path.endswith("/simulations")
        ):
            continue
        for method, operation in item.items():
            responses = operation["responses"]
            assert "503" in responses, (path, method)
            assert "422" in responses, (path, method)
            success = next(code for code in responses if code.startswith("2"))
            if success != "204":
                assert "content" in responses[success], (path, method)
            if "{job_id}" in path or "{scenario_id}" in path:
                assert "404" in responses, (path, method)

    submit = paths["/api/v1/grids/{grid_id}/simulations"]["post"]
    assert {"200", "202", "400", "404", "412", "422"} <= set(submit["responses"])
    headers = {parameter["name"] for parameter in submit["parameters"]}
    assert {"if-match", "idempotency-key"} <= headers
    assert "nothing reaches any equipment" in submit["description"]
    assert "409" in paths["/api/v1/simulations/{job_id}/cancel"]["post"]["responses"]
    assert "409" in paths["/api/v1/simulations/{job_id}/result"]["get"]["responses"]
    assert (
        "never reproduces"
        in paths["/api/v1/simulations/{job_id}/reproductions"]["get"]["description"]
    )
    assert (
        "sends nothing to any real equipment" in paths["/api/v1/scenarios"]["post"]["description"]
    )


async def test_no_response_schema_names_a_forbidden_field(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    for name, component in schema["components"]["schemas"].items():
        if name.startswith(("Job", "Scenario", "Result", "Reproduction", "Summary", "Attempt")):
            assert not set(component.get("properties", {})) & FORBIDDEN_FIELDS, name
