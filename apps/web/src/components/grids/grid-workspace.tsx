"use client";

import Link from "next/link";
import { Suspense } from "react";
import { AssetInventory } from "@/components/assets/asset-inventory";
import { DeleteGrid } from "@/components/grids/delete-grid";
import { GridOverview } from "@/components/grids/grid-overview";
import { GridSettings } from "@/components/grids/grid-settings";
import { DataOriginBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DevTenantNotice } from "@/components/ui/dev-tenant-notice";
import { ErrorState } from "@/components/ui/error-state";
import { Notice } from "@/components/ui/notice";
import { Tabs } from "@/components/ui/tabs";
import { fetchGrid } from "@/lib/resources/grids";
import { fetchTopology } from "@/lib/resources/topology";
import { type GridData, useGridData } from "@/lib/use-grid-data";

export type GridTab = "overview" | "assets" | "settings";

function tabHref(id: string, tab: GridTab): string {
  return tab === "overview" ? `/grid/${id}` : `/grid/${id}/${tab}`;
}

function Workspace({ data, tab, reload }: { data: GridData; tab: GridTab; reload: () => void }) {
  const { grid, topology } = data;
  return (
    <>
      <div className="mb-4">
        <p className="text-sm">
          <Link href="/grid" className="text-accent hover:underline">
            Grids
          </Link>
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{grid.name}</h1>
          <DataOriginBadge origin={grid.dataOrigin} />
          <span className="text-sm tabular-nums text-muted">Version {grid.version}</span>
        </div>
        {grid.description === "" ? null : (
          <p className="mt-1 max-w-3xl text-sm text-muted">{grid.description}</p>
        )}
      </div>

      {topology.version === grid.version ? null : (
        <div className="mb-4">
          <Notice tone="warn" title="The grid changed while this page loaded" role="status">
            <p>
              The details are version {grid.version}; the network is version {topology.version}.
              Reload to see one version.
            </p>
            <Button className="mt-2" onClick={reload}>
              Reload
            </Button>
          </Notice>
        </div>
      )}

      <Tabs
        label="Grid sections"
        current={tabHref(grid.id, tab)}
        tabs={[
          { href: tabHref(grid.id, "overview"), label: "Overview" },
          { href: tabHref(grid.id, "assets"), label: "Assets" },
          { href: tabHref(grid.id, "settings"), label: "Settings" },
        ]}
      />

      {tab === "overview" ? <GridOverview data={data} /> : null}
      {tab === "assets" ? (
        <Suspense fallback={<p className="text-sm text-muted">Loading assets…</p>}>
          <AssetInventory gridId={grid.id} topology={topology} onSaved={reload} />
        </Suspense>
      ) : null}
      {tab === "settings" ? (
        <div className="space-y-8">
          <GridSettings grid={grid} onSaved={reload} />
          <DeleteGrid grid={grid} onReload={reload} />
        </div>
      ) : null}
    </>
  );
}

/** One grid: its header and tabs, over data loaded once for every tab. */
export function GridWorkspace({
  id,
  tab,
  loadGrid = fetchGrid,
  loadTopology = fetchTopology,
}: {
  id: string;
  tab: GridTab;
  loadGrid?: typeof fetchGrid;
  loadTopology?: typeof fetchTopology;
}) {
  const [state, reload] = useGridData(id, loadGrid, loadTopology);
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
        <Workspace data={state.data} tab={tab} reload={reload} />
      )}
    </>
  );
}
