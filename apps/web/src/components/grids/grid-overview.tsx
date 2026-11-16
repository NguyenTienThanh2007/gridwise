"use client";

import { Suspense } from "react";
import { NetworkExplorer } from "@/components/network/network-explorer";
import { LoadingState } from "@/components/ui/loading-state";
import { Property, PropertyList } from "@/components/ui/property-list";
import { Panel, Section } from "@/components/ui/section";
import { type Column, DataTable } from "@/components/ui/data-table";
import { formatTimestamp, shortHash } from "@/lib/format";
import {
  ELEMENT_TYPES,
  ELEMENT_TYPE_LABELS,
  type ElementType,
  totalElements,
} from "@/lib/resources/grids";
import type { GridData } from "@/lib/use-grid-data";

/** The Overview tab: the stored model's metadata, element counts and the network. */
export function GridOverview({ data: { grid, topology } }: { data: GridData }) {
  const columns: Column<ElementType>[] = [
    { header: "Element type", cell: (type) => ELEMENT_TYPE_LABELS[type] },
    { header: "Count", cell: (type) => grid.elementCounts[type], numeric: true },
  ];
  return (
    <>
      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="Stored model">
          <Panel className="py-1">
            <PropertyList>
              <Property label="Version">
                <span className="tabular-nums">{grid.version}</span>
              </Property>
              <Property label="Topology hash">
                <code title={grid.topologyHash}>{shortHash(grid.topologyHash)}</code>
              </Property>
              <Property label="Frequency">{grid.frequencyHz} Hz</Property>
              <Property label="Elements">
                <span className="tabular-nums">{totalElements(grid.elementCounts)}</span>
              </Property>
              <Property label="Created">{formatTimestamp(grid.createdAt)}</Property>
              <Property label="Updated">{formatTimestamp(grid.updatedAt)}</Property>
            </PropertyList>
          </Panel>
        </Section>

        <Section title="Elements">
          <DataTable
            caption="Elements by type"
            columns={columns}
            rows={[...ELEMENT_TYPES]}
            rowKey={(type) => type}
          />
        </Section>
      </div>

      <Suspense fallback={<LoadingState label="Loading network…" />}>
        <NetworkExplorer topology={topology} gridId={grid.id} />
      </Suspense>
    </>
  );
}
