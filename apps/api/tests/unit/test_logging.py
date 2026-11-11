import json
import logging

import pytest

from gridwise_api.config import LoggingSettings
from gridwise_api.logging import configure_logging, get_logger


def _configure(log_format: str = "json", log_level: str = "INFO") -> None:
    configure_logging(LoggingSettings(_env_file=None, log_format=log_format, log_level=log_level))


def _lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return [json.loads(line) for line in captured.out.splitlines()]


@pytest.mark.parametrize(
    "logger_name", ["uvicorn.error", "uvicorn", "alembic.runtime.migration", "sqlalchemy.pool"]
)
def test_standard_library_loggers_emit_json(
    capsys: pytest.CaptureFixture[str], logger_name: str
) -> None:
    if logger_name.startswith("uvicorn"):
        # Simulate uvicorn having installed its own plain-text handler first.
        logging.getLogger(logger_name).addHandler(logging.StreamHandler())
    _configure()
    logging.getLogger(logger_name).warning("Started %s process", "server")

    events = [event for event in _lines(capsys) if event.get("logger") == logger_name]
    if logger_name.startswith("uvicorn"):
        assert len(events) == 1  # the plain handler is gone, so no duplicate
    assert events[-1]["event"] == "Started server process"
    assert events[-1]["level"] == "warning"
    assert "timestamp" in events[-1]


def test_application_events_and_library_records_share_one_format(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure()
    get_logger("gridwise_api.test").info("app_event", detail=1)
    logging.getLogger("uvicorn.error").info("library event")
    app_event, library_event = _lines(capsys)
    assert {"event", "level", "timestamp"} <= app_event.keys()
    assert {"event", "level", "timestamp"} <= library_event.keys()


def test_exceptions_are_one_line_with_the_traceback_inside(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure()
    try:
        raise ValueError("bad thing")
    except ValueError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
        get_logger("gridwise_api.test").error("app_failure", exc_info=True)
    library_event, app_event = _lines(capsys)
    assert "ValueError: bad thing" in str(library_event["exception"])
    assert "ValueError: bad thing" in str(app_event["exception"])


def test_uvicorn_access_log_is_silenced_in_favour_of_the_request_middleware(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure()
    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET /health/live HTTP/1.1" 200')
    assert _lines(capsys) == []


def test_log_level_filters_both_kinds_of_logger(capsys: pytest.CaptureFixture[str]) -> None:
    _configure(log_level="WARNING")
    get_logger("gridwise_api.test").info("hidden")
    logging.getLogger("uvicorn.error").info("hidden")
    get_logger("gridwise_api.test").warning("shown")
    assert [event["event"] for event in _lines(capsys)] == ["shown"]


def test_reconfiguring_does_not_duplicate_output(capsys: pytest.CaptureFixture[str]) -> None:
    _configure()
    _configure()
    logging.getLogger("uvicorn.error").info("once")
    assert len(_lines(capsys)) == 1
