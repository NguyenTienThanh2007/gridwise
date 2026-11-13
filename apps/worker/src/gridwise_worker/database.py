"""The worker's only access to the database: the five worker functions (migration 0004).

Each call is its own short transaction. Every call about a held job first sets the tenant
context to that job's organisation; the functions refuse a job of any other tenant.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import ProgrammingError

from gridwise_worker.settings import WorkerSettings

_SET_TENANT = text("SELECT set_config('app.current_organization_id', :organization_id, true)")
_UNDEFINED_TABLE = "42P01"
_NO_PRIVILEGE = "42501"


@dataclass(frozen=True, slots=True, kw_only=True)
class Lease:
    job_id: UUID
    organization_id: UUID
    token: UUID
    attempt: int
    input_document: str
    input_hash: str
    configuration: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Completion:
    outcome: str
    engine_version: str
    solver_name: str
    solver_version: str
    engine_fingerprint: str
    result_document: str | None
    result_hash: str | None


def connect(settings: WorkerSettings) -> Engine:
    return create_engine(
        settings.worker_database_url.get_secret_value(),
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        hide_parameters=True,
    )


class WorkerDatabase:
    def __init__(self, engine: Engine, *, worker_id: str, lease_seconds: int) -> None:
        self._engine = engine
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds

    def schema_revision(self) -> str | None:
        with self._engine.connect() as connection:
            try:
                return connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            except ProgrammingError as error:
                # Never migrated, or migrated to a revision older than the one that grants
                # the worker anything: either way not a schema this worker can use.
                if getattr(error.orig, "sqlstate", None) in (_UNDEFINED_TABLE, _NO_PRIVILEGE):
                    return None
                raise

    def claim(self) -> Lease | None:
        with self._engine.begin() as connection:
            row = connection.execute(
                text("SELECT * FROM sim.claim_next_job(:worker_id, :lease_seconds)"),
                {"worker_id": self._worker_id, "lease_seconds": self._lease_seconds},
            ).one_or_none()
        if row is None:
            return None
        return Lease(
            job_id=row.job_id,
            organization_id=row.organization_id,
            token=row.lease_token,
            attempt=row.attempt,
            input_document=row.input_document,
            input_hash=row.input_hash,
            configuration=row.configuration,
        )

    def _held(self, lease: Lease, statement: str, values: dict[str, object]) -> bool:
        with self._engine.begin() as connection:
            connection.execute(_SET_TENANT, {"organization_id": str(lease.organization_id)})
            return bool(
                connection.execute(
                    text(statement),
                    {"job_id": lease.job_id, "token": lease.token, **values},
                ).scalar_one()
            )

    def heartbeat(self, lease: Lease) -> bool:
        return self._held(
            lease,
            "SELECT sim.heartbeat_job(:job_id, :token, :lease_seconds)",
            {"lease_seconds": self._lease_seconds},
        )

    def complete(self, lease: Lease, completion: Completion) -> bool:
        return self._held(
            lease,
            "SELECT sim.complete_job(:job_id, :token, :outcome, :engine_version, "
            ":solver_name, :solver_version, :engine_fingerprint, :document, :result_hash)",
            {
                "outcome": completion.outcome,
                "engine_version": completion.engine_version,
                "solver_name": completion.solver_name,
                "solver_version": completion.solver_version,
                "engine_fingerprint": completion.engine_fingerprint,
                "document": completion.result_document,
                "result_hash": completion.result_hash,
            },
        )

    def fail(self, lease: Lease, failure_code: str) -> bool:
        return self._held(
            lease, "SELECT sim.fail_job(:job_id, :token, :code)", {"code": failure_code}
        )

    def release(self, lease: Lease) -> bool:
        return self._held(lease, "SELECT sim.release_job(:job_id, :token)", {})
