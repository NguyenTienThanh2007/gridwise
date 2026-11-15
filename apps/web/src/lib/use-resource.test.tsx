import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/http/client";
import { type Loader, useResource } from "@/lib/use-resource";

const ok = (data: string): ApiResult<string> => ({
  ok: true,
  status: 200,
  data,
  etag: 2,
  location: null,
  headers: new Headers(),
});

describe("useResource", () => {
  it("loads, then reloads on request", async () => {
    let calls = 0;
    const load: Loader<string> = vi.fn(async () => ok(`answer ${++calls}`));
    const { result } = renderHook(() => useResource(load));
    expect(result.current[0]).toEqual({ status: "loading" });
    await waitFor(() =>
      expect(result.current[0]).toEqual({ status: "ready", data: "answer 1", etag: 2 }),
    );
    act(() => result.current[1]());
    expect(result.current[0]).toEqual({ status: "loading" });
    await waitFor(() => expect(result.current[0]).toMatchObject({ data: "answer 2" }));
  });

  it("aborts the request when the component goes away", async () => {
    let seen: AbortSignal | undefined;
    const load: Loader<string> = (signal) => {
      seen = signal;
      return new Promise(() => undefined);
    };
    const { unmount } = renderHook(() => useResource(load));
    unmount();
    expect(seen?.aborted).toBe(true);
  });

  it("never shows a late answer for a loader it no longer uses", async () => {
    let release: (value: ApiResult<string>) => void = () => undefined;
    const slow: Loader<string> = () => new Promise((resolve) => (release = resolve));
    const fast: Loader<string> = async () => ok("fast");
    const { result, rerender } = renderHook(({ load }) => useResource(load), {
      initialProps: { load: slow },
    });
    rerender({ load: fast });
    await waitFor(() => expect(result.current[0]).toMatchObject({ data: "fast" }));
    release(ok("slow"));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(result.current[0]).toMatchObject({ data: "fast" });
  });
});

describe("useResource with keepPrevious", () => {
  it("keeps the last answer on screen while reloading", async () => {
    let calls = 0;
    let release: (value: ApiResult<string>) => void = () => undefined;
    const load: Loader<string> = () =>
      ++calls === 1 ? Promise.resolve(ok("first")) : new Promise((resolve) => (release = resolve));
    const { result } = renderHook(() => useResource(load, { keepPrevious: true }));
    await waitFor(() => expect(result.current[0]).toMatchObject({ data: "first" }));
    act(() => result.current[1]());
    expect(result.current[0]).toMatchObject({ data: "first" });
    await act(async () => release(ok("second")));
    expect(result.current[0]).toMatchObject({ data: "second" });
  });
});
