"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { DataOriginBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { type Column, DataTable } from "@/components/ui/data-table";
import { DevTenantNotice } from "@/components/ui/dev-tenant-notice";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { formatTimestamp } from "@/lib/format";
import { type Grid, type GridPage, fetchGrids } from "@/lib/resources/grids";
import { type Loader, useResource } from "@/lib/use-resource";

export const PAGE_SIZE = 25;

function columns(section: "overview" | "assets"): Column<Grid>[] {
  return [
    {
      header: "Name",
      cell: (grid) => (
        <Link
          href={section === "assets" ? `/grid/${grid.id}/assets` : `/grid/${grid.id}`}
          className="font-medium text-accent hover:underline"
        >
          {grid.name}
        </Link>
      ),
    },
    { header: "Data", cell: (grid) => <DataOriginBadge origin={grid.dataOrigin} /> },
    { header: "Version", cell: (grid) => grid.version, numeric: true },
    { header: "Buses", cell: (grid) => grid.elementCounts.buses, numeric: true },
    { header: "Lines", cell: (grid) => grid.elementCounts.lines, numeric: true },
    { header: "Transformers", cell: (grid) => grid.elementCounts.transformers, numeric: true },
    { header: "Updated", cell: (grid) => formatTimestamp(grid.updatedAt) },
  ];
}

export function GridListView({
  load = fetchGrids,
  section = "overview",
  deleted = false,
}: {
  load?: typeof fetchGrids;
  /** Which page of a grid the names link to. */
  section?: "overview" | "assets";
  /** Arrived here after deleting a grid. */
  deleted?: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const loader = useCallback<Loader<GridPage>>(
    (signal) => load({ limit: PAGE_SIZE, offset }, signal),
    [load, offset],
  );
  const [state, reload] = useResource(loader);

  return (
    <>
      <DevTenantNotice />
      {deleted ? (
        <p role="status" className="mb-4 text-sm font-medium text-ok">
          The grid was deleted.
        </p>
      ) : null}
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-muted">
          Loading grids…
        </p>
      ) : state.status === "error" ? (
        <ErrorState failure={state.failure} resource="grids" onRetry={reload} />
      ) : state.data.total === 0 ? (
        <EmptyState title="No grids are stored yet">
          <p>
            Load the synthetic demonstration grid (the CIGRE medium-voltage benchmark) with{" "}
            <code className="rounded bg-surface px-1">make seed-demo</code>, then reload this page.
          </p>
        </EmptyState>
      ) : (
        <section aria-labelledby="grid-list-title">
          <h2 id="grid-list-title" className="sr-only">
            Stored grids
          </h2>
          <DataTable
            caption="Stored grids"
            columns={columns(section)}
            rows={state.data.items}
            rowKey={(grid) => grid.id}
          />
          <div className="mt-3 flex items-center justify-between gap-4 text-sm text-muted">
            <p>
              {state.data.items.length === 0
                ? `No grids on this page of ${state.data.total}`
                : `Grids ${state.data.offset + 1}–${state.data.offset + state.data.items.length} of ${state.data.total}`}
            </p>
            <div className="flex gap-2">
              <Button
                disabled={offset === 0}
                onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                disabled={state.data.offset + state.data.items.length >= state.data.total}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </section>
      )}
    </>
  );
}
