"""Request body size limit (pure ASGI, before any route reads the body).

A declared ``Content-Length`` above the limit is refused at once. A body without one
(chunked) is read here up to the limit and handed on; one byte more and it is refused. In
both cases the response is ``413`` with the usual error envelope, and the route never runs.

It has to happen here: FastAPI turns any exception raised while it reads a body into a
generic ``400``.
"""

from http import HTTPStatus

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gridwise_api.api.errors import error_response

_METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH"})


def _too_large(limit: int) -> JSONResponse:
    return error_response(
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "request_too_large",
        f"The request body exceeds {limit} bytes",
    )


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in _METHODS_WITH_BODY:
            await self._app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                length = -1
            if length > self._max_bytes:
                await _too_large(self._max_bytes)(scope, receive, send)
                return
            await self._app(scope, receive, send)
            return

        # No declared length: buffer up to the limit, then replay.
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await self._app(scope, _replay([], message), send)
                return
            body = message.get("body", b"")
            size += len(body)
            if size > self._max_bytes:
                await _too_large(self._max_bytes)(scope, receive, send)
                return
            chunks.append(body)
            if not message.get("more_body", False):
                break
        await self._app(scope, _replay(chunks, None), send)


def _replay(chunks: list[bytes], final: Message | None) -> Receive:
    pending: list[Message] = [
        {"type": "http.request", "body": b"".join(chunks), "more_body": False}
    ]
    if final is not None:
        pending = [final]

    async def receive() -> Message:
        if pending:
            return pending.pop(0)
        return {"type": "http.disconnect"}

    return receive
