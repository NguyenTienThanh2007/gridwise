"""One error shape for every failure, and one structured event for every crash.

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

Clients never receive stack traces, exception messages or echoed input.
"""

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gridwise_api.logging import get_logger

logger = get_logger("gridwise_api.errors")

_CODES = {
    HTTPStatus.BAD_REQUEST: "bad_request",
    HTTPStatus.UNAUTHORIZED: "unauthorized",
    HTTPStatus.FORBIDDEN: "forbidden",
    HTTPStatus.NOT_FOUND: "not_found",
    HTTPStatus.METHOD_NOT_ALLOWED: "method_not_allowed",
    HTTPStatus.CONFLICT: "conflict",
    HTTPStatus.PRECONDITION_FAILED: "precondition_failed",
    HTTPStatus.REQUEST_ENTITY_TOO_LARGE: "request_too_large",
    HTTPStatus.TOO_MANY_REQUESTS: "rate_limited",
}
INTERNAL_ERROR_MESSAGE = "Internal server error"


class ErrorDetail(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return value if isinstance(value, str) else None


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[ErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code, message=message, request_id=current_request_id(), details=details
        )
    )
    return JSONResponse(
        body.model_dump(exclude_none=True, mode="json"), status_code=status_code, headers=headers
    )


class ApiError(Exception):
    """A deliberate failure with its own code, raised by routes and dependencies."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: list[ErrorDetail] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101  (registered for this type)
    return error_response(
        exc.status_code, exc.code, exc.message, details=exc.details, headers=exc.headers
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101  (registered for this type)
    status = HTTPStatus(exc.status_code)
    message = exc.detail if isinstance(exc.detail, str) else status.phrase
    headers = dict(exc.headers) if exc.headers else None
    return error_response(
        exc.status_code, _CODES.get(status, "http_error"), message, headers=headers
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101  (registered for this type)
    errors: list[dict[str, Any]] = list(exc.errors())
    # Location, message and type only: the rejected input is never echoed back.
    details = [
        ErrorDetail(
            location=list(e.get("loc", ())),
            message=str(e.get("msg", "")),
            type=str(e.get("type", "")),
        )
        for e in errors
    ]
    return error_response(
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "validation_error",
        "Request validation failed",
        details=details,
    )


class UnhandledExceptionMiddleware:
    """Turns any uncaught exception into one structured log event and a JSON 500.

    It sits inside the CORS and request-context middleware, so the 500 still carries CORS
    headers and the ``X-Request-ID`` header, and is counted by the access log.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, tracking_send)
        except Exception as error:
            logger.error(
                "unhandled_exception",
                error_type=type(error).__name__,
                method=scope["method"],
                path=scope["path"],
                exc_info=True,
            )
            if response_started:
                # Headers are already on the wire; all we can do is abort the connection.
                raise
            response = error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", INTERNAL_ERROR_MESSAGE
            )
            await response(scope, receive, send)
