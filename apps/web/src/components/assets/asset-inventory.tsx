"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { AssetEditForm } from "@/components/assets/asset-edit-form";
import { AssetTable } from "@/components/assets/asset-table";
import { ElementInspector } from "@/components/network/element-inspector";
import { DataOriginBadge } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/fields";
import {
  type AssetFilters,
  STATE_FILTER_LABELS,
  assetRows,
  filterRows,
  readFilters,
  stateOptions,
  writeFilters,
} from "@/lib/assets/filter";
import { findElement } from "@/lib/network/graph";
import {
  type ElementRef,
  SELECTION_PARAMETER,
  formatElementRef,
  parseElementRef,
} from "@/lib/network/selection";
import { ELEMENT_TYPES, ELEMENT_TYPE_LABELS } from "@/lib/resources/grids";
import type { updateAsset } from "@/lib/resources/assets";
import type { Topology } from "@/lib/resources/topology";

/** The Assets tab: every element of the stored model, filters, details and editing. */
export function AssetInventory({
  gridId,
  topology,
  onSaved,
  update,
}: {
  gridId: string;
  topology: Topology;
  onSaved: () => void;
  update?: typeof updateAsset;
}) {
  const { network } = topology;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // The filters live here and are copied to the address. Reading them back from the address
  // would lose keystrokes and changes made before the router caught up.
  const [filters, setFilterState] = useState(() => readFilters(searchParams));
  const rows = useMemo(() => assetRows(network), [network]);
  const shown = filterRows(rows, filters);

  const requested = parseElementRef(searchParams.get(SELECTION_PARAMETER));
  const selected =
    requested !== null && findElement(network, requested) !== null ? requested : null;
  const element = selected === null ? null : findElement(network, selected);

  // Which element's form is open, and the last save, both tied to one element.
  const [editing, setEditing] = useState<string | null>(null);
  const [saved, setSaved] = useState<{ ref: string; version: number } | null>(null);
  const selectedKey = selected === null ? null : formatElementRef(selected);

  // Built from the live address, not from `searchParams`, which lags behind a replace.
  const current = () => new URLSearchParams(window.location.search);
  const navigate = (params: URLSearchParams) =>
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  const setFilters = (next: AssetFilters) => {
    setFilterState(next);
    navigate(writeFilters(current(), next));
  };
  const select = (ref: ElementRef) => {
    const params = current();
    params.set(SELECTION_PARAMETER, formatElementRef(ref));
    navigate(params);
  };

  return (
    <section aria-labelledby="assets-title">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="assets-title" className="mb-2 text-section-title">
          Assets
        </h2>
        <div className="flex items-center gap-2">
          <DataOriginBadge origin={topology.dataOrigin} />
          <p className="text-xs text-muted">Synthetic model data. Not measurements.</p>
        </div>
      </div>

      <div role="search" aria-label="Filter assets" className="mb-3 flex flex-wrap items-end gap-3">
        <Select
          label="Type"
          value={filters.type}
          onChange={(type) =>
            setFilters({
              ...filters,
              type,
              state: stateOptions(type).includes(filters.state) ? filters.state : "any",
            })
          }
          options={[
            { value: "all", label: `All types (${rows.length})` },
            ...ELEMENT_TYPES.map((type) => ({
              value: type,
              label: `${ELEMENT_TYPE_LABELS[type]} (${rows.filter((row) => row.type === type).length})`,
            })),
          ]}
        />
        <Select
          label="State"
          value={filters.state}
          onChange={(state) => setFilters({ ...filters, state })}
          options={stateOptions(filters.type).map((state) => ({
            value: state,
            label: STATE_FILTER_LABELS[state],
          }))}
        />
        <div>
          <label htmlFor="asset-search" className="block text-sm font-medium">
            Search name or key
          </label>
          <input
            id="asset-search"
            type="search"
            value={filters.query}
            onChange={(event) => setFilters({ ...filters, query: event.target.value })}
            className="mt-1 rounded-control border border-line px-2 py-1.5 text-sm"
          />
        </div>
        <p role="status" className="pb-1.5 text-sm text-muted">
          {shown.length} of {rows.length} elements
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="min-w-0">
          {shown.length === 0 ? (
            <EmptyState title="No element matches these filters">
              <Button onClick={() => setFilters({ type: "all", state: "any", query: "" })}>
                Clear filters
              </Button>
            </EmptyState>
          ) : (
            <AssetTable
              network={network}
              rows={shown}
              type={filters.type}
              selected={selected}
              onSelect={select}
            />
          )}
        </div>
        <div>
          <ElementInspector network={network} selected={selected} onSelect={select}>
            {selected === null || element === null || selectedKey === null ? null : (
              <>
                {saved?.ref === selectedKey ? (
                  <p role="status" className="mt-3 text-sm font-medium text-ok">
                    Saved. The grid is now version {saved.version}.
                  </p>
                ) : null}
                {editing === selectedKey ? (
                  <AssetEditForm
                    key={selectedKey}
                    gridId={gridId}
                    version={topology.version}
                    target={selected}
                    element={element}
                    update={update}
                    onCancel={() => setEditing(null)}
                    onReload={onSaved}
                    onSaved={(version) => {
                      setEditing(null);
                      setSaved({ ref: selectedKey, version });
                      onSaved();
                    }}
                  />
                ) : (
                  <Button className="mt-3" onClick={() => setEditing(selectedKey)}>
                    Edit
                  </Button>
                )}
              </>
            )}
          </ElementInspector>
        </div>
      </div>
    </section>
  );
}
