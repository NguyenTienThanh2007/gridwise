import re

import httpx
import pytest

from gridwise_api.api.middleware import resolve_request_id


async def test_response_carries_a_generated_request_id(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])


async def test_well_formed_caller_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "trace-123.abc_DEF"})
    assert response.headers["X-Request-ID"] == "trace-123.abc_DEF"


@pytest.mark.parametrize("bad", ["", "has space", "x" * 65, "line\nbreak", "<script>"])
def test_malformed_caller_request_id_is_replaced(bad: str) -> None:
    resolved = resolve_request_id(bad)
    assert resolved != bad
    assert re.fullmatch(r"[0-9a-f]{32}", resolved)


async def test_request_is_logged_with_its_request_id(
    client: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    await client.get("/health/live", headers={"X-Request-ID": "log-check-1"})
    line = next(row for row in capsys.readouterr().out.splitlines() if "http_request" in row)
    assert '"request_id": "log-check-1"' in line
    assert '"status_code": 200' in line
    assert '"path": "/health/live"' in line
