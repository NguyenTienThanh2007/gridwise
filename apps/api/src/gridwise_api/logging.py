"""Structured logging: every line this process writes is one event.

Both structlog events and standard-library records (uvicorn, Alembic, SQLAlchemy,
warnings) go through the same renderer, so container output is uniformly JSON.
"""

import logging
import sys
from typing import TextIO, cast

import structlog
from structlog.typing import FilteringBoundLogger, Processor

from gridwise_api.config import LoggingSettings

_HANDLER_NAME = "gridwise-structured"


class _CurrentStdout:
    """A stream that always writes to whatever ``sys.stdout`` is right now.

    Binding the real stream object at configuration time breaks as soon as something
    (a test harness, a supervisor) swaps ``sys.stdout`` afterwards.
    """

    def write(self, text: str) -> int:
        return sys.stdout.write(text)

    def flush(self) -> None:
        sys.stdout.flush()


def configure_logging(settings: LoggingSettings) -> None:
    stdout = _CurrentStdout()
    json_output = settings.log_format == "json"
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    # format_exc_info renders the traceback as text. It deliberately does not capture
    # local variables, which could hold credentials.
    final: list[Processor] = (
        [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
        if json_output
        else [structlog.dev.ConsoleRenderer()]
    )

    structlog.configure(
        processors=[*shared, *final],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=cast(TextIO, stdout)),
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(cast(TextIO, stdout))
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[*shared, structlog.stdlib.add_logger_name],
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *final],
        )
    )
    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    logging.captureWarnings(True)

    # Uvicorn installs its own plain-text handlers before the app factory runs.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # The request middleware already writes one access event per request.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False

    # Statement logging would be both noisy and a place for data to leak.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> FilteringBoundLogger:
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger
