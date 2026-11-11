import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from gridwise_api.api.errors import INTERNAL_ERROR_MESSAGE

SECRET = "hunter2-super-secret"  # noqa: S105  (a marker value, not a credential)


@pytest.fixture
def failing_app(app: FastAPI) -> FastAPI:
    @app.get("/test/boom")
    async def boom() -> None:
        local_credential = SECRET  # must never reach the client or the log
        raise RuntimeError(f"upstream refused {len(local_credential)} bytes")

    @app.get("/test/forbidden")
    async def forbidden() -> None:
        raise HTTPException(status_code=403, detail="Not allowed here")

    @app.get("/test/number")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    return app


@pytest.fixture
async def failing_client(failing_app: FastAPI) -> httpx.AsyncClient:
    # raise_app_exceptions=True (the default) also proves nothing escapes the app.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=failing_app), base_url="http://test")


def _events(output: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]


async def test_unhandled_exception_returns_a_json_500_with_the_request_id(
    capsys: pytest.CaptureFixture[str], failing_client: httpx.AsyncClient
) -> None:
    response = await failing_client.get("/test/boom", headers={"X-Request-ID": "req-500"})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.headers["X-Request-ID"] == "req-500"
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": INTERNAL_ERROR_MESSAGE,
            "request_id": "req-500",
        }
    }


async def test_unhandled_exception_details_never_reach_the_client(
    failing_client: httpx.AsyncClient,
) -> None:
    response = await failing_client.get("/test/boom")
    for leaked in ("RuntimeError", "upstream refused", "Traceback", SECRET, "test_errors.py"):
        assert leaked not in response.text


async def test_unhandled_exception_is_logged_as_exactly_one_structured_error_event(
    capsys: pytest.CaptureFixture[str], failing_client: httpx.AsyncClient
) -> None:
    await failing_client.get("/test/boom", headers={"X-Request-ID": "req-log"})
    output = capsys.readouterr()
    events = _events(output.out)  # every line must parse as JSON

    errors = [event for event in events if event["level"] == "error"]
    assert len(errors) == 1
    error = errors[0]
    assert error["event"] == "unhandled_exception"
    assert error["request_id"] == "req-log"
    assert error["error_type"] == "RuntimeError"
    assert error["path"] == "/test/boom"
    assert "RuntimeError: upstream refused" in str(error["exception"])

    access = [event for event in events if event["event"] == "http_request"]
    assert [event["status_code"] for event in access] == [500]
    assert access[0]["request_id"] == "req-log"

    # Tracebacks carry no local variables, and nothing was written outside the JSON stream.
    assert SECRET not in output.out
    assert output.err == ""


async def test_cors_headers_survive_an_unhandled_exception(
    failing_client: httpx.AsyncClient,
) -> None:
    response = await failing_client.get("/test/boom", headers={"Origin": "http://localhost:3100"})
    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3100"


async def test_http_errors_use_the_same_shape(failing_client: httpx.AsyncClient) -> None:
    missing = await failing_client.get("/nope", headers={"X-Request-ID": "req-404"})
    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "not_found", "message": "Not Found", "request_id": "req-404"}
    }

    wrong_method = await failing_client.post("/health/live")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"
    assert wrong_method.headers["allow"] == "GET"

    forbidden = await failing_client.get("/test/forbidden")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"] == {
        "code": "forbidden",
        "message": "Not allowed here",
        "request_id": forbidden.headers["X-Request-ID"],
    }


async def test_validation_errors_do_not_echo_the_rejected_input(
    failing_client: httpx.AsyncClient,
) -> None:
    response = await failing_client.get("/test/number", params={"value": SECRET})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == [
        {
            "location": ["query", "value"],
            "message": "Input should be a valid integer, unable to parse string as an integer",
            "type": "int_parsing",
        }
    ]
    assert SECRET not in response.text
