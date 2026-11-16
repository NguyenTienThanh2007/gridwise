"use client";

import Link from "next/link";
import { PageHeader } from "@/components/page-header";
import { useCallback, useState } from "react";
import {
  JobStatusBadge,
  statusExplanation,
  statusLabel,
} from "@/components/simulations/job-status";
import { Button } from "@/components/ui/button";
import { type Column, DataTable } from "@/components/ui/data-table";
import { ErrorState, describeFailure } from "@/components/ui/error-state";
import { Notice } from "@/components/ui/notice";
import { formatTimestamp, shortHash, shortId } from "@/lib/format";
import type { ApiFailure, ApiResult } from "@/lib/http/client";
import { isUuid } from "@/lib/resources/decode";
import { describeModification } from "@/lib/resources/scenarios";
import {
  type Attempt,
  type Job,
  cancelJob,
  fetchJob,
  isTerminal,
} from "@/lib/resources/simulations";
import { usePolling } from "@/lib/use-polling";
import { useGrids } from "@/components/simulations/use-names";
import type { fetchGrids } from "@/lib/resources/grids";
import type { Loader } from "@/lib/use-resource";
import { LoadingState } from "@/components/ui/loading-state";
import { Property, PropertyList } from "@/components/ui/property-list";
import { Panel } from "@/components/ui/section";

const NOT_A_JOB_ID: ApiResult<Job> = {
  ok: false,
  failure: { kind: "not_found", code: "job_not_found", message: "Not a job id" },
};

const done = (job: Job) => isTerminal(job.status);

const ALGORITHMS: Record<string, string> = { newton_raphson: "AC Newton-Raphson" };

const ENDED_BY: Record<string, string> = {
  lease_expired: "Worker stopped responding",
  completed: "Completed",
  failed: "Failed",
  released: "Released at shutdown",
};

const ATTEMPT_COLUMNS: Column<Attempt>[] = [
  { header: "Attempt", cell: (a) => a.attempt, numeric: true },
  {
    header: "Started",
    cell: (a) => <span className="whitespace-nowrap">{formatTimestamp(a.startedAt)}</span>,
  },
  {
    header: "Ended",
    cell: (a) =>
      a.endedAt === null ? (
        "–"
      ) : (
        <span className="whitespace-nowrap">{formatTimestamp(a.endedAt)}</span>
      ),
  },
  {
    header: "How it ended",
    cell: (a) => (a.endedBy === null ? "Still running" : (ENDED_BY[a.endedBy] ?? a.endedBy)),
  },
];

const SOURCE_TEXT = {
  current: "The grid is still at this version.",
  changed: "The grid has been edited since; this job keeps the version it captured.",
  deleted: "The grid has since been deleted; this job keeps its own copy.",
} as const;

function CancelControl({
  job,
  onDone,
  cancel,
}: {
  job: Job;
  onDone: () => void;
  cancel: typeof cancelJob;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  if (job.status !== "queued" && failure === null) return null;

  const run = async () => {
    setBusy(true);
    setFailure(null);
    const result = await cancel(job.id);
    setBusy(false);
    setConfirming(false);
    if (!result.ok) setFailure(result.failure);
    onDone();
  };

  return (
    <div className="mt-3">
      {failure !== null ? (
        <Notice tone="warn" title="Not cancelled" role="alert">
          <p>
            {failure.kind === "conflict" && failure.status === 409
              ? `The job is already ${failure.details[0]?.type ?? "past the queue"}: only a queued job can be cancelled.`
              : describeFailure(failure, "job").detail}
          </p>
          <Button className="mt-2" onClick={() => setFailure(null)}>
            Dismiss
          </Button>
        </Notice>
      ) : confirming ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm">Cancel this queued job? It will not be solved.</p>
          <Button variant="danger" disabled={busy} onClick={() => void run()}>
            {busy ? "Cancelling…" : "Confirm cancel"}
          </Button>
          <Button disabled={busy} onClick={() => setConfirming(false)}>
            Keep it
          </Button>
        </div>
      ) : (
        <Button onClick={() => setConfirming(true)}>Cancel job</Button>
      )}
    </div>
  );
}

function JobDetails({
  job,
  gridName,
  polling,
  refreshFailure,
  onRefresh,
  cancel,
}: {
  job: Job;
  gridName: string | null;
  polling: boolean;
  refreshFailure: ApiFailure | null;
  onRefresh: () => void;
  cancel: typeof cancelJob;
}) {
  const modifications = job.scenario.specification.modifications;
  return (
    <>
      <PageHeader
        breadcrumbs={[{ href: "/simulations", label: "Simulations" }]}
        title={
          <>
            Simulation job <code className="font-normal text-muted">{shortId(job.id)}</code>
          </>
        }
        meta={<JobStatusBadge job={job} />}
        summary="A power-flow simulation of a stored synthetic model. Results are simulated, not measured. Nothing is sent to any equipment."
      />

      <section
        aria-labelledby="job-status-title"
        className="max-w-3xl rounded-panel border border-line bg-panel p-4"
      >
        <h2 id="job-status-title" className="text-section-title">
          Status
        </h2>
        <div aria-live="polite">
          <p className="mt-1 text-lg font-semibold">{statusLabel(job)}</p>
          <p className="mt-1 text-sm">{statusExplanation(job)}</p>
        </div>
        {polling ? (
          <p className="mt-2 text-xs text-muted">
            Following this job: it is checked again every few seconds while this tab is visible.
          </p>
        ) : null}
        {refreshFailure === null ? null : (
          <p className="mt-2 text-xs font-medium text-warn" role="status">
            Could not refresh ({describeFailure(refreshFailure, "job").title.toLowerCase()}). Trying
            again; the status above may be out of date.
          </p>
        )}
        <CancelControl job={job} onDone={onRefresh} cancel={cancel} />
      </section>

      {job.status === "completed" ? (
        <section aria-labelledby="job-result-title" className="mt-6 max-w-3xl">
          <h2 id="job-result-title" className="mb-2 text-section-title">
            Result
          </h2>
          <div className="rounded-panel border border-dashed border-line bg-panel p-4 text-sm text-muted">
            {job.outcome === "not_converged"
              ? "This run did not converge: there are no values, and none will be shown."
              : "The result is stored. Its summary, element values and reproduction history are shown here from P1.4e."}
          </div>
        </section>
      ) : null}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="job-input-title">
          <h2 id="job-input-title" className="mb-2 text-section-title">
            What was simulated
          </h2>
          <Panel className="py-1">
            <PropertyList>
              <Property label="Grid">
                {job.source.gridId === null ? (
                  <span className="text-muted">Deleted grid</span>
                ) : (
                  <Link href={`/grid/${job.source.gridId}`} className="text-accent hover:underline">
                    {gridName ?? "Open grid"}
                  </Link>
                )}
                <span className="tabular-nums">, version {job.source.gridVersion}</span>
                <p className="text-xs text-muted">{SOURCE_TEXT[job.source.status]}</p>
              </Property>
              <Property label="Scenario">
                {modifications.length === 0 ? (
                  "Normal operation (no changes)"
                ) : (
                  <>
                    {job.scenario.id === null ? (
                      <p className="text-xs text-muted">
                        The scenario was deleted; this job keeps its copy.
                      </p>
                    ) : null}
                    <ul className="list-disc pl-5">
                      {modifications.map((modification, index) => (
                        <li key={index}>{describeModification(modification)}</li>
                      ))}
                    </ul>
                  </>
                )}
              </Property>
              <Property label="Solver options">
                {ALGORITHMS[job.configuration.algorithm] ?? job.configuration.algorithm}, tolerance{" "}
                {job.configuration.toleranceMva} MVA, at most {job.configuration.maxIterations}{" "}
                iterations
              </Property>
              <Property label="Input snapshot">
                <code title={job.inputSnapshotHash}>{shortHash(job.inputSnapshotHash)}</code>
              </Property>
            </PropertyList>
          </Panel>
        </section>

        <section aria-labelledby="job-run-title">
          <h2 id="job-run-title" className="mb-2 text-section-title">
            How it ran
          </h2>
          <Panel className="py-1">
            <PropertyList>
              <Property label="Submitted">{formatTimestamp(job.createdAt)}</Property>
              <Property label="Started">
                {job.startedAt === null ? "–" : formatTimestamp(job.startedAt)}
              </Property>
              <Property label="Finished">
                {job.finishedAt === null ? "–" : formatTimestamp(job.finishedAt)}
              </Property>
              {job.cancelledAt === null ? null : (
                <Property label="Cancelled">{formatTimestamp(job.cancelledAt)}</Property>
              )}
              <Property label="Engine">
                {job.engine.executedVersion === null
                  ? `Requested ${job.engine.requestedVersion}`
                  : `${job.engine.executedVersion} (requested ${job.engine.requestedVersion})`}
              </Property>
              <Property label="Solver">
                {job.engine.solverName === null
                  ? "–"
                  : `${job.engine.solverName} ${job.engine.solverVersion ?? ""}`}
              </Property>
            </PropertyList>
          </Panel>
        </section>
      </div>

      <section aria-labelledby="job-attempts-title" className="mt-6 max-w-3xl">
        <h2 id="job-attempts-title" className="mb-2 text-section-title">
          Attempts
        </h2>
        {job.attempts === null || job.attempts.length === 0 ? (
          <p className="text-sm text-muted">No worker has started this job yet.</p>
        ) : (
          <DataTable
            caption="Attempts"
            columns={ATTEMPT_COLUMNS}
            rows={job.attempts}
            rowKey={(a) => String(a.attempt)}
          />
        )}
      </section>
    </>
  );
}

/** One simulation job, followed until it ends. */
export function JobView({
  id,
  load = fetchJob,
  cancel = cancelJob,
  loadGrids,
}: {
  id: string;
  load?: typeof fetchJob;
  cancel?: typeof cancelJob;
  loadGrids?: typeof fetchGrids;
}) {
  const loader = useCallback<Loader<Job>>(
    (signal) => (isUuid(id) ? load(id, signal) : Promise.resolve(NOT_A_JOB_ID)),
    [id, load],
  );
  const [state, refresh] = usePolling(loader, done);
  const [grids] = useGrids(loadGrids);

  return (
    <>
      {state.status === "loading" ? (
        <LoadingState label="Loading job…" />
      ) : state.status === "error" ? (
        <>
          <PageHeader
            breadcrumbs={[{ href: "/simulations", label: "Simulations" }]}
            title={state.failure.kind === "not_found" ? "Job not found" : "Simulation job"}
          />
          <ErrorState failure={state.failure} resource="job" onRetry={refresh} />
          <p className="mt-4 text-sm">
            <Link href="/simulations" className="text-accent hover:underline">
              Back to all simulations
            </Link>
          </p>
        </>
      ) : (
        <JobDetails
          job={state.data}
          gridName={
            grids.status === "ready"
              ? (grids.data.find((grid) => grid.id === state.data.source.gridId)?.name ?? null)
              : null
          }
          polling={state.polling}
          refreshFailure={state.refreshFailure}
          onRefresh={refresh}
          cancel={cancel}
        />
      )}
    </>
  );
}
