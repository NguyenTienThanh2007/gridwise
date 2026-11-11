"""Request ID propagation and access logging (pure ASGI, no body buffering)."""

import re
import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gridwise_api.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

logger = get_logger("gridwise_api.access")


def resolve_request_id(candidate: str | None) -> str:
    """Accept a well-formed caller ID; otherwise mint one (never log raw input)."""
    if candidate is not None and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = resolve_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        status_code = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self._app(scope, receive, send_with_request_id)
            finally:
                logger.info(
                    "http_request",
                    method=scope["method"],
                    path=scope["path"],
                    status_code=status_code,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )
