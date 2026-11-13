"""Requests for a host the API does not serve are refused (DNS rebinding)."""

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from gridwise_api.api.hosts import host_name
from gridwise_api.config import Settings


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("localhost", "localhost"),
        ("localhost:8020", "localhost"),
        ("LocalHost:8020", "localhost"),
        ("127.0.0.1:8000", "127.0.0.1"),
        ("[::1]:8020", "::1"),
        ("[::1]", "::1"),
        ("evil.example.test", "evil.example.test"),
    ],
)
def test_the_host_name_is_taken_without_the_port(header: str, expected: str) -> None:
    assert host_name(header) == expected


@pytest.mark.parametrize("host", ["localhost:8020", "127.0.0.1:8000", "[::1]:8020", "LOCALHOST"])
async def test_the_configured_hosts_are_served(app: FastAPI, host: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/health/live", headers={"Host": host})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "evil.example.test",
        "evil.example.test:8020",
        "localhost.evil.example.test",
        "127.0.0.1.nip.io",
        "",
    ],
)
async def test_any_other_host_is_refused_everywhere(app: FastAPI, host: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        for method, path in (
            ("GET", "/health/live"),
            ("GET", "/api/v1/grids"),
            ("POST", "/api/v1/grids"),
            ("DELETE", "/api/v1/grids/00000000-0000-4000-8000-000000000000"),
        ):
            response = await client.request(method, path, headers={"Host": host})
            assert response.status_code == 400, (method, path)
            body = response.json()
            assert body["error"]["code"] == "invalid_host"
            assert body["error"]["request_id"]
            if host:
                assert host not in response.text


@pytest.mark.parametrize("hosts", [["*"], ["*.example.test"], [""], []])
def test_allowed_hosts_must_be_explicit(hosts: list[str]) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://a:b@localhost/db",
            allowed_hosts=hosts,
        )


def test_the_default_serves_the_local_machine_only() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://a:b@localhost/db")
    assert settings.allowed_hosts == ["localhost", "127.0.0.1", "::1"]
