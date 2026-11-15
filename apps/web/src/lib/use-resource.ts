"use client";

import { useCallback, useEffect, useState } from "react";
import type { ApiFailure, ApiResult } from "@/lib/http/client";

export type ResourceState<T> =
  | { status: "loading" }
  | { status: "error"; failure: ApiFailure }
  | { status: "ready"; data: T; etag: number | null };

export type Loader<T> = (signal: AbortSignal) => Promise<ApiResult<T>>;

interface Settled<T> {
  /** The loader and attempt this result belongs to: anything else is still loading. */
  load: Loader<T>;
  attempt: number;
  state: ResourceState<T>;
}

/**
 * Loads one resource when `load` changes (memoise it with `useCallback`), and again on
 * `reload()`. The request is aborted when the component unmounts or the loader changes, and
 * a late answer never overwrites a newer one.
 *
 * With `keepPrevious`, a reload of the same loader keeps the last answer on screen until the
 * new one arrives, instead of showing "loading": forms below it keep their state.
 */
export function useResource<T>(
  load: Loader<T>,
  { keepPrevious = false }: { keepPrevious?: boolean } = {},
): [ResourceState<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setSettled({
        load,
        attempt,
        state: result.ok
          ? { status: "ready", data: result.data, etag: result.etag }
          : { status: "error", failure: result.failure },
      });
    });
    return () => controller.abort();
  }, [load, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const current = settled !== null && settled.load === load && settled.attempt === attempt;
  const kept = keepPrevious && settled !== null && settled.load === load;
  return [current || kept ? settled.state : { status: "loading" }, reload];
}
