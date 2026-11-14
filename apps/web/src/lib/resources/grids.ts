/**
 * Grids: `GET /api/v1/grids` and `GET /api/v1/grids/{id}` (decision 0009).
 *
 * Field names and meanings are the API's. `dataOrigin` is decoded from the response, never
 * assumed: only "synthetic" exists so far, and anything else fails to decode rather than
 * being shown under the wrong label.
 */

import { type ApiResult, request } from "@/lib/http/client";
import {
  type Record_,
  decoder,
  int,
  list,
  num,
  oneOf,
  record,
  str,
  timestamp,
  uuid,
} from "@/lib/resources/decode";

export const DATA_ORIGINS = ["synthetic"] as const;
export type DataOrigin = (typeof DATA_ORIGINS)[number];

export const ELEMENT_TYPES = [
  "buses",
  "lines",
  "transformers",
  "loads",
  "generators",
  "external_grids",
  "switches",
] as const;
export type ElementType = (typeof ELEMENT_TYPES)[number];

export const ELEMENT_TYPE_LABELS: Record<ElementType, string> = {
  buses: "Buses",
  lines: "Lines",
  transformers: "Transformers",
  loads: "Loads",
  generators: "Generators",
  external_grids: "External grids",
  switches: "Switches",
};

export type ElementCounts = Record<ElementType, number>;

export interface Grid {
  id: string;
  name: string;
  description: string;
  frequencyHz: number;
  dataOrigin: DataOrigin;
  /** Also the grid's ETag: send it as If-Match to change the grid. */
  version: number;
  topologyHash: string;
  elementCounts: ElementCounts;
  createdAt: string;
  updatedAt: string;
}

export interface GridPage {
  items: Grid[];
  total: number;
  limit: number;
  offset: number;
}

function readCounts(value: unknown): ElementCounts {
  const object = record(value, "element_counts");
  return Object.fromEntries(
    ELEMENT_TYPES.map((type) => [type, int(object, type)]),
  ) as ElementCounts;
}

export function readGrid(value: unknown): Grid {
  const object: Record_ = record(value, "grid");
  return {
    id: uuid(object, "id"),
    name: str(object, "name"),
    description: str(object, "description"),
    frequencyHz: num(object, "frequency_hz"),
    dataOrigin: oneOf(object, "data_origin", DATA_ORIGINS),
    version: int(object, "version"),
    topologyHash: str(object, "topology_hash"),
    elementCounts: readCounts(object.element_counts),
    createdAt: timestamp(object, "created_at"),
    updatedAt: timestamp(object, "updated_at"),
  };
}

export const decodeGrid = decoder(readGrid);

export const decodeGridPage = decoder((value): GridPage => {
  const object = record(value, "grid list");
  return {
    items: list(object, "items", readGrid),
    total: int(object, "total"),
    limit: int(object, "limit"),
    offset: int(object, "offset"),
  };
});

export function fetchGrids(
  { limit, offset }: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<ApiResult<GridPage>> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request(`/api/v1/grids?${query}`, decodeGridPage, { signal });
}

export function fetchGrid(id: string, signal?: AbortSignal): Promise<ApiResult<Grid>> {
  return request(`/api/v1/grids/${encodeURIComponent(id)}`, decodeGrid, { signal });
}

export function totalElements(counts: ElementCounts): number {
  return ELEMENT_TYPES.reduce((sum, type) => sum + counts[type], 0);
}
