"use client";

import { useCallback } from "react";
import { fetchGrids, type Grid } from "@/lib/resources/grids";
import { fetchScenarios, type Scenario } from "@/lib/resources/scenarios";
import { type Loader, useResource } from "@/lib/use-resource";

/** Up to 100 grids and scenarios, the API's largest page: enough to name and choose them. */
export const PICK_LIMIT = 100;

export function useGrids(load: typeof fetchGrids = fetchGrids) {
  const loader = useCallback<Loader<Grid[]>>(
    async (signal) => {
      const result = await load({ limit: PICK_LIMIT, offset: 0 }, signal);
      return result.ok ? { ...result, data: result.data.items } : result;
    },
    [load],
  );
  return useResource(loader, { keepPrevious: true });
}

export function useScenarios(load: typeof fetchScenarios = fetchScenarios) {
  const loader = useCallback<Loader<Scenario[]>>(
    async (signal) => {
      const result = await load({ limit: PICK_LIMIT, offset: 0 }, signal);
      return result.ok ? { ...result, data: result.data.items } : result;
    },
    [load],
  );
  return useResource(loader, { keepPrevious: true });
}
