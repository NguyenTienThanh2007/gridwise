"""Reading simulation results: the stored document, checked, and its summary.

Pure reads through the API role, under row-level security. Nothing here runs a power flow.
A job that did not converge has a summary with no values; a job that has not completed has
no result at all.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from gridwise_api.repositories import simulations as repository
from gridwise_api.services.simulations import JobNotFoundError, StoredDataIntegrityError
from gridwise_api.tenancy import tenant_transaction
from gridwise_grid_engine.hashing import sha256_hex
from gridwise_grid_engine.result_summaries import (
    NOT_CONVERGED,
    ResultDocumentError,
    ResultSummary,
    summarize_result_document,
)


class ResultNotAvailableError(Exception):
    """The job has not completed (queued, running, failed or cancelled)."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"a {status} job has no result")


@dataclass(frozen=True, slots=True, kw_only=True)
class JobResult:
    job_id: UUID
    outcome: str
    result_hash: str | None
    summary: ResultSummary
    #: The canonical result document; None when the job did not converge.
    document: str | None


class ResultService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, organization_id: UUID, job_id: UUID) -> JobResult:
        async with tenant_transaction(self._engine, organization_id) as session:
            job = await repository.get_job(session, job_id)
            if job is None:
                raise JobNotFoundError
            row = (
                await session.execute(
                    text(
                        "SELECT document, document_hash, result_hash FROM sim.results "
                        "WHERE organization_id = :organization_id AND job_id = :job_id"
                    ),
                    {"organization_id": organization_id, "job_id": job_id},
                )
            ).one_or_none()
        if job.status != "completed":
            raise ResultNotAvailableError(job.status)
        if job.outcome == "not_converged":
            if row is not None:  # the worker functions never store one
                raise StoredDataIntegrityError
            return JobResult(
                job_id=job_id,
                outcome="not_converged",
                result_hash=None,
                summary=NOT_CONVERGED,
                document=None,
            )
        if row is None or sha256_hex(row.document) != row.document_hash:
            raise StoredDataIntegrityError
        try:
            summary = summarize_result_document(row.document)
        except ResultDocumentError as error:
            raise StoredDataIntegrityError from error
        return JobResult(
            job_id=job_id,
            outcome="converged",
            result_hash=row.result_hash,
            summary=summary,
            document=row.document,
        )
