"""Host header check (pure ASGI).

The API has no authentication yet and listens on localhost. A web page the developer visits
can point its own domain at 127.0.0.1 (DNS rebinding) and become same-origin with the API,
which gets around CORS entirely. The page cannot change the Host header its browser sends,
though: it is the page's own domain. Refusing every Host that is not configured closes that
path.

Refused requests get ``400 invalid_host`` in the usual error envelope. The value is not
echoed back.
"""

from http import HTTPStatus

from starlette.types import ASGIApp, Receive, Scope, Send

from gridwise_api.api.errors import error_response


def host_name(header: str) -> str:
    """The host part of a Host header, lower case, without the port."""
    value = header.strip().lower()
    if value.startswith("["):  # IPv6 literal: [::1]:8020
        end = value.find("]")
        return value[1:end] if end != -1 else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class TrustedHostMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_hosts: list[str]) -> None:
        self._app = app
        self._allowed = frozenset(host.strip().lower().strip("[]") for host in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        raw = dict(scope["headers"]).get(b"host", b"")
        if host_name(raw.decode("latin-1")) not in self._allowed:
            response = error_response(
                HTTPStatus.BAD_REQUEST,
                "invalid_host",
                "The Host header names a host this API does not serve",
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)
