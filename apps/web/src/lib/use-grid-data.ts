"use client";

import { useCallback } from "react";
import type { ApiResult } from "@/lib/http/client";
import { isUuid } from "@/lib/resources/decode";
import { type Grid, fetchGrid } from "@/lib/resources/grids";
import { type Topology, fetchTopology } from "@/lib/resources/topology";
import { type Loader, type ResourceState, useResource } from "@/lib/use-resource";

export interface GridData {
  grid: Grid;
  topology: Topology;
}

const NOT_A_GRID_ID: ApiResult<GridData> = {
  ok: false,
  failure: { kind: "not_found", code: "grid_not_found", message: "Not a grid id" },
};

/**
 * A grid's details and its whole network, loaded together, so every tab shows the same
 * version. `reload()` keeps the current data on screen until the new answer arrives, so an
 * open form keeps what the user typed.
 */
export function useGridData(
  id: string,
  loadGrid: typeof fetchGrid = fetchGrid,
  loadTopology: typeof fetchTopology = fetchTopology,
): [ResourceState<GridData>, () => void] {
  const loader = useCallback<Loader<GridData>>(
    async (signal) => {
      // An id that is not a UUID cannot name a grid: no request is made for it.
      if (!isUuid(id)) return NOT_A_GRID_ID;
      const [grid, topology] = await Promise.all([loadGrid(id, signal), loadTopology(id, signal)]);
      if (!grid.ok) return grid;
      if (!topology.ok) return topology;
      return { ...grid, data: { grid: grid.data, topology: topology.data } };
    },
    [id, loadGrid, loadTopology],
  );
  return useResource(loader, { keepPrevious: true });
}
