"""Delete old, finished simulations, deliberately. Nothing is deleted automatically.

    python -m gridwise_api.retention --finished-before 2026-01-01T00:00:00Z \\
        [--organization ID] [--limit 1000] [--apply]

Without ``--apply`` it only reports what would be deleted. With it, for each eligible job in
its own transaction: its reproductions and attempts (cascade), its result, the job itself;
then every snapshot no remaining job refers to.

Rules:

* Only jobs that ended (completed, failed, cancelled) before the cutoff are eligible; queued
  and running jobs never are. A job is re-checked under a row lock before it is deleted.
* Grids and scenarios are never touched. A snapshot still used by any job is kept; foreign
  keys refuse anything else, so a concurrent submission can never lose its input.
* Runs as the owner role (``GRIDWISE_MIGRATION_DATABASE_URL``), like migrations: the API's
  role cannot delete simulation data at all.
* Prints one JSON line with the counts; logs every deleted job id.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from gridwise_api.config import MigrationSettings
from gridwise_api.logging import configure_logging, get_logger

logger = get_logger("gridwise_api.retention")

_TERMINAL = "('completed', 'failed', 'cancelled')"


@dataclass(slots=True)
class RetentionReport:
    applied: bool
    jobs: int = 0
    results: int = 0
    reproductions: int = 0
    attempts: int = 0
    snapshots: int = 0
    skipped: int = 0


async def eligible_jobs(
    engine: AsyncEngine, *, finished_before: datetime, organization_id: UUID | None, limit: int
) -> list[tuple[UUID, UUID]]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                f"SELECT id, organization_id FROM sim.jobs WHERE status IN {_TERMINAL} "  # noqa: S608
                "AND finished_at < :cutoff "
                "AND (CAST(:organization_id AS uuid) IS NULL "
                "     OR organization_id = CAST(:organization_id AS uuid)) "
                "ORDER BY finished_at, id LIMIT :limit"
            ),
            {
                "cutoff": finished_before,
                "organization_id": str(organization_id) if organization_id else None,
                "limit": limit,
            },
        )
        return [(row.id, row.organization_id) for row in rows]


async def _counts(engine: AsyncEngine, jobs: list[tuple[UUID, UUID]]) -> dict[str, int]:
    ids = [job for job, _ in jobs]
    async with engine.connect() as connection:
        values = {}
        for table in ("results", "reproductions", "job_attempts"):
            values[table] = (
                await connection.execute(
                    text(f"SELECT count(*) FROM sim.{table} WHERE job_id = ANY(:ids)"),  # noqa: S608
                    {"ids": ids},
                )
            ).scalar_one()
        values["snapshots"] = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM sim.snapshots s WHERE s.id IN ("
                    "  SELECT base_snapshot_id FROM sim.jobs WHERE id = ANY(:ids) UNION "
                    "  SELECT input_snapshot_id FROM sim.jobs WHERE id = ANY(:ids)) "
                    "AND NOT EXISTS (SELECT 1 FROM sim.jobs j WHERE NOT (j.id = ANY(:ids)) "
                    "  AND j.organization_id = s.organization_id "
                    "  AND (j.base_snapshot_id = s.id OR j.input_snapshot_id = s.id))"
                ),
                {"ids": ids},
            )
        ).scalar_one()
    return values


async def apply_retention(
    engine: AsyncEngine,
    *,
    finished_before: datetime,
    organization_id: UUID | None = None,
    limit: int = 1000,
    apply: bool = False,
) -> RetentionReport:
    jobs = await eligible_jobs(
        engine, finished_before=finished_before, organization_id=organization_id, limit=limit
    )
    report = RetentionReport(applied=apply)
    if not apply:
        counts = await _counts(engine, jobs)
        report.jobs = len(jobs)
        report.results = counts["results"]
        report.reproductions = counts["reproductions"]
        report.attempts = counts["job_attempts"]
        report.snapshots = counts["snapshots"]
        return report

    for job_id, job_organization in jobs:
        try:
            async with engine.begin() as connection:
                locked = (
                    await connection.execute(
                        text(
                            f"SELECT base_snapshot_id, input_snapshot_id FROM sim.jobs "  # noqa: S608
                            f"WHERE id = :id AND status IN {_TERMINAL} AND finished_at < :cutoff "
                            "FOR UPDATE"
                        ),
                        {"id": job_id, "cutoff": finished_before},
                    )
                ).one_or_none()
                if locked is None:
                    report.skipped += 1
                    continue
                for table, field in (
                    ("reproductions", "reproductions"),
                    ("job_attempts", "attempts"),
                ):
                    deleted = await connection.execute(
                        text(f"DELETE FROM sim.{table} WHERE job_id = :id"),  # noqa: S608
                        {"id": job_id},
                    )
                    setattr(report, field, getattr(report, field) + deleted.rowcount)
                deleted = await connection.execute(
                    text("DELETE FROM sim.results WHERE job_id = :id"), {"id": job_id}
                )
                report.results += deleted.rowcount
                await connection.execute(
                    text("DELETE FROM sim.jobs WHERE id = :id"), {"id": job_id}
                )
                report.jobs += 1
                # Snapshots this job used, unless another job still refers to them.
                deleted = await connection.execute(
                    text(
                        "DELETE FROM sim.snapshots s WHERE s.organization_id = :organization_id "
                        "AND s.id IN (:base, :input) "
                        "AND NOT EXISTS (SELECT 1 FROM sim.jobs j "
                        "  WHERE j.organization_id = s.organization_id "
                        "  AND (j.base_snapshot_id = s.id OR j.input_snapshot_id = s.id))"
                    ),
                    {
                        "organization_id": job_organization,
                        "base": locked.base_snapshot_id,
                        "input": locked.input_snapshot_id,
                    },
                )
                report.snapshots += deleted.rowcount
            logger.info(
                "retention_deleted_job", job_id=str(job_id), organization_id=str(job_organization)
            )
        except IntegrityError:
            # A snapshot became referenced meanwhile (a concurrent submission): this job's
            # deletion is rolled back as a whole and retried on a later run.
            report.skipped += 1
            logger.warning("retention_skipped_job", job_id=str(job_id))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m gridwise_api.retention",
        description="Delete finished simulations that ended before a cutoff (dry run by default).",
    )
    parser.add_argument("--finished-before", required=True, type=datetime.fromisoformat)
    parser.add_argument("--organization", type=UUID)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--apply", action="store_true", help="delete; without it, only report")
    arguments = parser.parse_args(argv)
    if arguments.finished_before.tzinfo is None:
        parser.error("--finished-before needs a time zone, for example 2026-01-01T00:00:00Z")
    if not 1 <= arguments.limit <= 100_000:
        parser.error("--limit must be between 1 and 100000")

    settings = MigrationSettings()
    configure_logging(settings)

    async def run() -> RetentionReport:
        engine = create_async_engine(
            settings.migration_database_url.get_secret_value(), hide_parameters=True
        )
        try:
            return await apply_retention(
                engine,
                finished_before=arguments.finished_before,
                organization_id=arguments.organization,
                limit=arguments.limit,
                apply=arguments.apply,
            )
        finally:
            await engine.dispose()

    report = asyncio.run(run())
    print(json.dumps(asdict(report), sort_keys=True))  # noqa: T201  (the command's output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
