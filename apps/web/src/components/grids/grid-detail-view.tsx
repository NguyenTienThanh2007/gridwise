"use client";

import Link from "next/link";
import { type ReactNode, Suspense, useCallback } from "react";
import { NetworkExplorer } from "@/components/network/network-explorer";
import { DataOriginBadge } from "@/components/ui/badge";
import { type Column, DataTable } from "@/components/ui/data-table";
import { DevTenantNotice } from "@/components/ui/dev-tenant-notice";
import { ErrorState } from "@/components/ui/error-state";
import { formatTimestamp, shortHash } from "@/lib/format";
import type { ApiResult } from "@/lib/http/client";
import { isUuid } from "@/lib/resources/decode";
import {
  ELEMENT_TYPES,
  ELEMENT_TYPE_LABELS,
  type ElementType,
  type Grid,
  fetchGrid,
  totalElements,
} from "@/lib/resources/grids";
import { fetchTopology } from "@/lib/resources/topology";
import { type Loader, useResource } from "@/lib/use-resource";

const NOT_A_GRID_ID: ApiResult<Grid> = {
  ok: false,
  failure: { kind: "not_found", code: "grid_not_found", message: "Not a grid id" },
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-t border-line py-2 sm:grid sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="text-sm sm:col-span-2">{children}</dd>
    </div>
  );
}

function GridDetail({ grid, loadTopology }: { grid: Grid; loadTopology: typeof fetchTopology }) {
  const columns: Column<ElementType>[] = [
    { header: "Element type", cell: (type) => ELEMENT_TYPE_LABELS[type] },
    { header: "Count", cell: (type) => grid.elementCounts[type], numeric: true },
  ];
  return (
    <>
      <div className="mb-6">
        <p className="text-sm">
          <Link href="/grid" className="text-accent hover:underline">
            Grids
          </Link>
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{grid.name}</h1>
          <DataOriginBadge origin={grid.dataOrigin} />
        </div>
        {grid.description === "" ? null : (
          <p className="mt-1 max-w-3xl text-sm text-muted">{grid.description}</p>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="grid-metadata-title">
          <h2 id="grid-metadata-title" className="mb-2 text-sm font-medium text-muted">
            Stored model
          </h2>
          <dl className="rounded-lg border border-line bg-panel px-4">
            <Field label="Version">
              <span className="tabular-nums">{grid.version}</span>
            </Field>
            <Field label="Topology hash">
              <code title={grid.topologyHash}>{shortHash(grid.topologyHash)}</code>
            </Field>
            <Field label="Frequency">{grid.frequencyHz} Hz</Field>
            <Field label="Elements">
              <span className="tabular-nums">{totalElements(grid.elementCounts)}</span>
            </Field>
            <Field label="Created">{formatTimestamp(grid.createdAt)}</Field>
            <Field label="Updated">{formatTimestamp(grid.updatedAt)}</Field>
          </dl>
        </section>

        <section aria-labelledby="grid-elements-title">
          <h2 id="grid-elements-title" className="mb-2 text-sm font-medium text-muted">
            Elements
          </h2>
          <DataTable
            caption="Elements by type"
            columns={columns}
            rows={[...ELEMENT_TYPES]}
            rowKey={(type) => type}
          />
        </section>
      </div>

      <Suspense fallback={<p className="mt-8 text-sm text-muted">Loading network…</p>}>
        <NetworkExplorer gridId={grid.id} gridVersion={grid.version} load={loadTopology} />
      </Suspense>
    </>
  );
}

export function GridDetailView({
  id,
  load = fetchGrid,
  loadTopology = fetchTopology,
}: {
  id: string;
  load?: typeof fetchGrid;
  loadTopology?: typeof fetchTopology;
}) {
  const loader = useCallback<Loader<Grid>>(
    // An id that is not a UUID cannot name a grid: no request is made for it.
    (signal) => (isUuid(id) ? load(id, signal) : Promise.resolve(NOT_A_GRID_ID)),
    [id, load],
  );
  const [state, reload] = useResource(loader);

  return (
    <>
      <DevTenantNotice />
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-muted">
          Loading grid…
        </p>
      ) : state.status === "error" ? (
        <>
          <h1 className="mb-4 text-2xl font-semibold">
            {state.failure.kind === "not_found" ? "Grid not found" : "Grid"}
          </h1>
          <ErrorState failure={state.failure} resource="grid" onRetry={reload} />
          <p className="mt-4 text-sm">
            <Link href="/grid" className="text-accent hover:underline">
              Back to all grids
            </Link>
          </p>
        </>
      ) : (
        <GridDetail grid={state.data} loadTopology={loadTopology} />
      )}
    </>
  );
}
