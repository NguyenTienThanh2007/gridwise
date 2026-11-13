"""Worker configuration. It sees its own database URL only."""

import os
import socket
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator

from gridwise_api.config import DATABASE_URL_SCHEME, LoggingSettings


def _default_worker_id() -> str:
    host = "".join(c if c.isalnum() or c in "._-" else "-" for c in socket.gethostname())
    return f"{host[:60] or 'worker'}:{os.getpid()}"


class WorkerSettings(LoggingSettings):
    # Credentials of the worker role (gridwise_worker): no superuser, no BYPASSRLS, no table
    # privileges; it may only execute the worker functions (migration 0004).
    worker_database_url: SecretStr
    worker_id: str = Field(default_factory=_default_worker_id, pattern=r"^[A-Za-z0-9._:-]{1,100}$")

    worker_job_timeout_seconds: float = Field(default=120.0, gt=0, le=3600)
    worker_lease_seconds: int = Field(default=60, ge=5, le=3600)
    worker_heartbeat_seconds: float = Field(default=10.0, gt=0, le=600)
    worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    worker_max_backoff_seconds: float = Field(default=30.0, gt=0, le=600)
    worker_shutdown_grace_seconds: float = Field(default=20.0, ge=0, le=600)
    worker_health_file: str = "/tmp/gridwise-worker-alive"  # noqa: S108  (container-local)
    worker_health_max_age_seconds: float = Field(default=30.0, gt=0, le=600)
    # Test hook: which solver the child builds. Only "pandapower", or a factory in the
    # test suite ("tests.<module>:<name>"), so configuration cannot load arbitrary code.
    worker_solver: str = Field(
        default="pandapower",
        pattern=r"^(pandapower|tests\.[A-Za-z0-9_.]+:[A-Za-z_][A-Za-z0-9_]*)$",
    )

    @field_validator("worker_database_url")
    @classmethod
    def _psycopg_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(DATABASE_URL_SCHEME):
            raise ValueError(f"worker_database_url must start with {DATABASE_URL_SCHEME}")
        return value

    @model_validator(mode="after")
    def _heartbeat_well_inside_the_lease(self) -> Self:
        if self.worker_heartbeat_seconds * 3 > self.worker_lease_seconds:
            raise ValueError("worker_heartbeat_seconds must be at most a third of the lease")
        return self
