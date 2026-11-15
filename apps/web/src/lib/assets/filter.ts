/**
 * The asset inventory's rows and filters. Filters are kept in the address
 * (`?type=lines&state=out_of_service&q=6-7`), like the explorer's selection.
 */

import { type NetworkElement, elementsOf, naturalCompare } from "@/lib/network/graph";
import { ELEMENT_TYPES, type ElementType } from "@/lib/resources/grids";
import type { Network } from "@/lib/resources/topology";

export const STATE_FILTERS = ["any", "in_service", "out_of_service", "open", "closed"] as const;
export type StateFilter = (typeof STATE_FILTERS)[number];

export const STATE_FILTER_LABELS: Record<StateFilter, string> = {
  any: "Any state",
  in_service: "In service",
  out_of_service: "Out of service",
  open: "Switch model position open",
  closed: "Switch model position closed",
};

export interface AssetFilters {
  type: ElementType | "all";
  state: StateFilter;
  query: string;
}

export const DEFAULT_FILTERS: AssetFilters = { type: "all", state: "any", query: "" };

/** Switches have a model position and no service state; everything else the reverse. */
export function stateOptions(type: AssetFilters["type"]): StateFilter[] {
  if (type === "switches") return ["any", "open", "closed"];
  if (type === "all") return [...STATE_FILTERS];
  return ["any", "in_service", "out_of_service"];
}

export function readFilters(params: URLSearchParams): AssetFilters {
  const type = ELEMENT_TYPES.find((candidate) => candidate === params.get("type")) ?? "all";
  const requested = STATE_FILTERS.find((candidate) => candidate === params.get("state")) ?? "any";
  return {
    type,
    state: stateOptions(type).includes(requested) ? requested : "any",
    query: params.get("q") ?? "",
  };
}

/** The filters written into existing parameters; defaults are left out of the address. */
export function writeFilters(params: URLSearchParams, filters: AssetFilters): URLSearchParams {
  const next = new URLSearchParams(params.toString());
  const set = (name: string, value: string, fallback: string) =>
    value === fallback ? next.delete(name) : next.set(name, value);
  set("type", filters.type, "all");
  set("state", filters.state, "any");
  set("q", filters.query, "");
  return next;
}

export interface AssetRow {
  type: ElementType;
  element: NetworkElement;
}

export function assetRows(network: Network): AssetRow[] {
  return ELEMENT_TYPES.flatMap((type) =>
    [...elementsOf(network, type)]
      .sort((a, b) => naturalCompare(a.key, b.key))
      .map((element) => ({ type, element })),
  );
}

function matchesState(element: NetworkElement, state: StateFilter): boolean {
  switch (state) {
    case "any":
      return true;
    case "open":
    case "closed":
      return "closed" in element && element.closed === (state === "closed");
    case "in_service":
    case "out_of_service":
      return "inService" in element && element.inService === (state === "in_service");
  }
}

export function filterRows(rows: AssetRow[], filters: AssetFilters): AssetRow[] {
  const needle = filters.query.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (filters.type === "all" || row.type === filters.type) &&
      matchesState(row.element, filters.state) &&
      (needle === "" ||
        row.element.key.toLowerCase().includes(needle) ||
        row.element.name.toLowerCase().includes(needle)),
  );
}
