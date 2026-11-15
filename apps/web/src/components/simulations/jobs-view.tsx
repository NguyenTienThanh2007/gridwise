"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { JobStatusBadge } from "@/components/simulations/job-status";
import { useGrids, useScenarios } from "@/components/simulations/use-names";
import { Button } from "@/components/ui/button";
import { type Column, DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Select } from "@/components/ui/fields";
import { formatTimestamp, shortHash, shortId } from "@/lib/format";
import { isUuid } from "@/lib/resources/decode";
import type { fetchGrids } from "@/lib/resources/grids";
import type { fetchScenarios } from "@/lib/resources/scenarios";
import {
  JOB_STATUSES,
  type Job,
  type JobFilters,
  type JobPage,
  type JobStatus,
  fetchJobs,
} from "@/lib/resources/simulations";
import { type Loader, useResource } from "@/lib/use-resource";

export const JOBS_PAGE_SIZE = 25;

function readJobFilters(params: URLSearchParams): JobFilters {
  const grid = params.get("grid");
  return {
    gridId: grid !== null && isUuid(grid) ? grid : null,
    status: JOB_STATUSES.find((status) => status === params.get("status")) ?? null,
  };
}

/** Every simulation job of this organisation, newest first. Refreshed on request only. */
export function JobsView({
  load = fetchJobs,
  loadGrids,
  loadScenarios,
}: {
  load?: typeof fetchJobs;
  loadGrids?: typeof fetchGrids;
  loadScenarios?: typeof fetchScenarios;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [filters, setFilterState] = useState(() => readJobFilters(searchParams));
  const [offset, setOffset] = useState(0);
  const loader = useCallback<Loader<JobPage>>(
    (signal) => load({ limit: JOBS_PAGE_SIZE, offset, ...filters }, signal),
    [load, offset, filters],
  );
  const [state, reload] = useResource(loader, { keepPrevious: true });
  const [grids] = useGrids(loadGrids);
  const [scenarios] = useScenarios(loadScenarios);

  const gridName = (id: string | null) =>
    id === null
      ? null
      : grids.status === "ready"
        ? (grids.data.find((grid) => grid.id === id)?.name ?? null)
        : null;
  const scenarioName = (job: Job) => {
    if (job.scenario.specification.modifications.length === 0) return "Normal operation";
    if (job.scenario.id === null) return "Deleted scenario";
    const found =
      scenarios.status === "ready"
        ? scenarios.data.find((s) => s.id === job.scenario.id)
        : undefined;
    return found?.name ?? "Scenario";
  };

  const setFilters = (next: JobFilters) => {
    setFilterState(next);
    setOffset(0);
    const params = new URLSearchParams(window.location.search);
    if (next.gridId === null) params.delete("grid");
    else params.set("grid", next.gridId);
    if (next.status === null) params.delete("status");
    else params.set("status", next.status);
    const query = params.toString();
    router.replace(query === "" ? pathname : `${pathname}?${query}`, { scroll: false });
  };

  const columns: Column<Job>[] = [
    {
      header: "Job",
      cell: (job) => (
        <Link
          href={`/simulations/${job.id}`}
          className="whitespace-nowrap font-medium text-accent hover:underline"
          aria-label={`Job ${job.id}`}
        >
          <code>{shortId(job.id)}</code>
        </Link>
      ),
    },
    { header: "Status", cell: (job) => <JobStatusBadge job={job} /> },
    {
      header: "Grid",
      cell: (job) =>
        job.source.gridId === null ? (
          <span className="text-muted">Deleted grid</span>
        ) : (
          <>
            {gridName(job.source.gridId) ?? (
              <code className="text-xs">{shortHash(job.source.gridId, 8)}</code>
            )}
            <span className="ml-1 text-xs text-muted">v{job.source.gridVersion}</span>
          </>
        ),
    },
    { header: "Scenario", cell: scenarioName },
    {
      header: "Submitted",
      cell: (job) => <span className="whitespace-nowrap">{formatTimestamp(job.createdAt)}</span>,
    },
    {
      header: "Finished",
      cell: (job) =>
        job.finishedAt === null ? (
          "–"
        ) : (
          <span className="whitespace-nowrap">{formatTimestamp(job.finishedAt)}</span>
        ),
    },
  ];

  return (
    <section aria-labelledby="jobs-title">
      <h2 id="jobs-title" className="sr-only">
        Simulation jobs
      </h2>
      <div role="search" aria-label="Filter jobs" className="mb-3 flex flex-wrap items-end gap-3">
        <Select
          label="Grid"
          value={filters.gridId ?? "all"}
          onChange={(value) => setFilters({ ...filters, gridId: value === "all" ? null : value })}
          options={[
            { value: "all", label: "All grids" },
            ...(grids.status === "ready"
              ? grids.data.map((grid) => ({ value: grid.id, label: grid.name }))
              : []),
            // Keep a filter from the address selectable even before the names arrive.
            ...(filters.gridId !== null &&
            (grids.status !== "ready" || !grids.data.some((grid) => grid.id === filters.gridId))
              ? [{ value: filters.gridId, label: `Grid ${shortHash(filters.gridId, 8)}` }]
              : []),
          ]}
        />
        <Select<JobStatus | "all">
          label="Status"
          value={filters.status ?? "all"}
          onChange={(value) => setFilters({ ...filters, status: value === "all" ? null : value })}
          options={[
            { value: "all", label: "Any status" },
            ...JOB_STATUSES.map((status) => ({
              value: status,
              label: status.charAt(0).toUpperCase() + status.slice(1),
            })),
          ]}
        />
        <Button onClick={reload}>Refresh</Button>
        <Link
          href="/simulations/new"
          className="rounded border border-accent bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent/90"
        >
          New simulation
        </Link>
      </div>

      {state.status === "loading" ? (
        <p role="status" className="text-sm text-muted">
          Loading jobs…
        </p>
      ) : state.status === "error" ? (
        <ErrorState failure={state.failure} resource="jobs" onRetry={reload} />
      ) : state.data.total === 0 ? (
        <EmptyState
          title={
            filters.gridId === null && filters.status === null
              ? "No simulation has been submitted yet"
              : "No job matches these filters"
          }
        >
          <p>
            <Link href="/simulations/new" className="text-accent hover:underline">
              Submit a simulation
            </Link>{" "}
            of a stored grid.
          </p>
        </EmptyState>
      ) : (
        <>
          <DataTable
            caption="Simulation jobs, newest first"
            columns={columns}
            rows={state.data.items}
            rowKey={(job) => job.id}
          />
          <div className="mt-3 flex items-center justify-between gap-4 text-sm text-muted">
            <p>
              Jobs {state.data.offset + 1}–{state.data.offset + state.data.items.length} of{" "}
              {state.data.total}. This list does not refresh by itself.
            </p>
            <div className="flex gap-2">
              <Button
                disabled={offset === 0}
                onClick={() => setOffset((v) => Math.max(0, v - JOBS_PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                disabled={state.data.offset + state.data.items.length >= state.data.total}
                onClick={() => setOffset((v) => v + JOBS_PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
