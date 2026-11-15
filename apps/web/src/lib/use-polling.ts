"use client";

import { useCallback, useEffect, useState } from "react";
import type { ApiFailure } from "@/lib/http/client";
import type { Loader } from "@/lib/use-resource";

/**
 * How long to wait before asking again (decision 0014, section 9): every second for the
 * first ten seconds, every two seconds until thirty, then every five.
 */
export function pollDelay(elapsedMs: number): number {
  if (elapsedMs < 10_000) return 1_000;
  if (elapsedMs < 30_000) return 2_000;
  return 5_000;
}

export type PollState<T> =
  | { status: "loading" }
  | { status: "error"; failure: ApiFailure }
  | {
      status: "ready";
      data: T;
      /** Still asking: the data is not final yet. */
      polling: boolean;
      /** The last refresh failed; the data shown is the last good answer. */
      refreshFailure: ApiFailure | null;
    };

interface Settled<T> {
  load: Loader<T>;
  attempt: number;
  state: PollState<T>;
}

/**
 * Asks `load` until `isDone` says the answer is final. At most one request at a time; none
 * while the tab is hidden (it asks again as soon as the tab is visible); none after the
 * component is gone. A failed refresh keeps the last answer on screen and tries again.
 * `isDone` must be stable (a module-level function).
 */
export function usePolling<T>(
  load: Loader<T>,
  isDone: (data: T) => boolean,
): [PollState<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    let stopped = false;
    let finished = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let last: T | null = null;
    const started = Date.now();
    const settle = (state: PollState<T>) => setSettled({ load, attempt, state });

    const tick = async () => {
      if (stopped || finished || inFlight) return;
      if (document.visibilityState === "hidden") return; // resumed by onVisibility
      inFlight = true;
      controller = new AbortController();
      const result = await load(controller.signal);
      inFlight = false;
      if (stopped) return;
      if (result.ok) {
        last = result.data;
        finished = isDone(result.data);
        settle({ status: "ready", data: result.data, polling: !finished, refreshFailure: null });
      } else if (result.failure.kind === "aborted") {
        return;
      } else if (last === null || result.failure.kind === "not_found") {
        finished = true;
        settle({ status: "error", failure: result.failure });
      } else {
        settle({ status: "ready", data: last, polling: true, refreshFailure: result.failure });
      }
      if (!finished) timer = setTimeout(() => void tick(), pollDelay(Date.now() - started));
    };
    const onVisibility = () => {
      if (document.visibilityState !== "visible" || finished || inFlight) return;
      clearTimeout(timer);
      void tick();
    };

    document.addEventListener("visibilitychange", onVisibility);
    void tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load, isDone, attempt]);

  const refresh = useCallback(() => setAttempt((value) => value + 1), []);
  const current = settled !== null && settled.load === load;
  // A refresh keeps the last answer on screen until the new one arrives.
  return [current ? settled.state : { status: "loading" }, refresh];
}
