/**
 * Writes to a stored grid (decision 0009): one asset's name and state, the grid's name and
 * description, and deleting the grid. Every write sends If-Match with the version the user
 * saw; the API refuses a stale one with 412 and never applies it.
 *
 * Only what the API accepts can be sent: a switch takes `name` and `closed` (its position in
 * the stored simulation model, not a command to any equipment); every other element takes
 * `name` and `in_service`. Electrical parameters are not editable here.
 */

import { type ApiResult, noContent, request } from "@/lib/http/client";
import { decoder, int, oneOf, record, str, uuid } from "@/lib/resources/decode";
import { ELEMENT_TYPES, type ElementType, type Grid, decodeGrid } from "@/lib/resources/grids";
import {
  type Bus,
  type ExternalGrid,
  type Generator,
  type Line,
  type Load,
  type Switch,
  type Transformer,
  readBus,
  readExternalGrid,
  readGenerator,
  readLine,
  readLoad,
  readSwitch,
  readTransformer,
} from "@/lib/resources/topology";

type Asset = Bus | Line | Transformer | Load | Generator | ExternalGrid | Switch;

const READERS: Record<ElementType, (value: unknown) => Asset> = {
  buses: readBus,
  lines: readLine,
  transformers: readTransformer,
  loads: readLoad,
  generators: readGenerator,
  external_grids: readExternalGrid,
  switches: readSwitch,
};

export interface AssetResponse {
  gridId: string;
  gridVersion: number;
  topologyHash: string;
  type: ElementType;
  asset: Asset;
}

/** The asset is read with the reader of the type the response states. */
export const decodeAssetResponse = decoder((value): AssetResponse => {
  const object = record(value, "asset response");
  const type = oneOf(object, "type", ELEMENT_TYPES);
  return {
    gridId: uuid(object, "grid_id"),
    gridVersion: int(object, "grid_version"),
    topologyHash: str(object, "topology_hash"),
    type,
    asset: READERS[type](object.asset),
  };
});

export type AssetChange =
  | { kind: "switch"; name?: string; closed?: boolean }
  | { kind: "element"; name?: string; inService?: boolean };

export function assetChangeBody(change: AssetChange): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (change.name !== undefined) body.name = change.name;
  if (change.kind === "switch" && change.closed !== undefined) body.closed = change.closed;
  if (change.kind === "element" && change.inService !== undefined) {
    body.in_service = change.inService;
  }
  return body;
}

export function updateAsset(
  gridId: string,
  type: ElementType,
  key: string,
  change: AssetChange,
  expectedVersion: number,
): Promise<ApiResult<AssetResponse>> {
  const path = `/api/v1/grids/${encodeURIComponent(gridId)}/assets/${type}/${encodeURIComponent(key)}`;
  return request(path, decodeAssetResponse, {
    method: "PATCH",
    body: assetChangeBody(change),
    ifMatch: expectedVersion,
  });
}

export function updateGrid(
  gridId: string,
  change: { name?: string; description?: string },
  expectedVersion: number,
): Promise<ApiResult<Grid>> {
  return request(`/api/v1/grids/${encodeURIComponent(gridId)}`, decodeGrid, {
    method: "PATCH",
    body: change,
    ifMatch: expectedVersion,
  });
}

export function deleteGrid(gridId: string, expectedVersion: number): Promise<ApiResult<true>> {
  return request(`/api/v1/grids/${encodeURIComponent(gridId)}`, noContent, {
    method: "DELETE",
    ifMatch: expectedVersion,
  });
}

/** The same limits as the API's `Name` and `Description` (schemas/grids.py). */
export const NAME_MAX = 200;
export const DESCRIPTION_MAX = 2000;

export function nameError(value: string): string | null {
  if (value.trim() === "") return "Enter a name.";
  if (value.length > NAME_MAX) return `Use at most ${NAME_MAX} characters.`;
  return null;
}

export function descriptionError(value: string): string | null {
  return value.length > DESCRIPTION_MAX ? `Use at most ${DESCRIPTION_MAX} characters.` : null;
}
