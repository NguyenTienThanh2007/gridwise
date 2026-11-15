"use client";

import { type ReactNode, Suspense } from "react";
import { NetworkExplorer } from "@/components/network/network-explorer";
import { type Column, DataTable } from "@/components/ui/data-table";
import { formatTimestamp, shortHash } from "@/lib/format";
import {
  ELEMENT_TYPES,
  ELEMENT_TYPE_LABELS,
  type ElementType,
  totalElements,
} from "@/lib/resources/grids";
import type { GridData } from "@/lib/use-grid-data";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-t border-line py-2 first:border-t-0 sm:grid sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="text-sm sm:col-span-2">{children}</dd>
    </div>
  );
}

/** The Overview tab: the stored model's metadata, element counts and the network. */
export function GridOverview({ data: { grid, topology } }: { data: GridData }) {
  const columns: Column<ElementType>[] = [
    { header: "Element type", cell: (type) => ELEMENT_TYPE_LABELS[type] },
    { header: "Count", cell: (type) => grid.elementCounts[type], numeric: true },
  ];
  return (
    <>
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
        <NetworkExplorer topology={topology} gridId={grid.id} />
      </Suspense>
    </>
  );
}
