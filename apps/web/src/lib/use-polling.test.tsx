import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ApiResult } from "@/lib/http/client";
import { pollDelay, usePolling } from "@/lib/use-polling";
import type { Loader } from "@/lib/use-resource";

const ok = (status: string): ApiResult<{ status: string }> => ({
  ok: true,
  status: 200,
  data: { status },
  etag: null,
  location: null,
  headers: new Headers(),
});
const done = (data: { status: string }) => data.status === "completed";

let visibility: DocumentVisibilityState = "visible";
beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
});
afterEach(() => vi.useRealTimers());

const flush = () =>
  act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

describe("pollDelay", () => {
  it("asks every second, then every two, then every five", () => {
    expect([0, 9_999, 10_000, 29_999, 30_000, 600_000].map(pollDelay)).toEqual([
      1000, 1000, 2000, 2000, 5000, 5000,
    ]);
  });
});

describe("usePolling", () => {
  it("asks until the answer is final, then stops", async () => {
    const answers = ["queued", "running", "completed"];
    const load = vi.fn<Loader<{ status: string }>>(async () => ok(answers.shift() ?? "completed"));
    const { result } = renderHook(() => usePolling(load, done));
    await flush();
    expect(result.current[0]).toMatchObject({
      status: "ready",
      data: { status: "queued" },
      polling: true,
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current[0]).toMatchObject({ data: { status: "running" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current[0]).toMatchObject({ data: { status: "completed" }, polling: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(load).toHaveBeenCalledTimes(3);
  });

  it("does not ask while the tab is hidden, and asks again when it is shown", async () => {
    const load = vi.fn<Loader<{ status: string }>>(async () => ok("queued"));
    renderHook(() => usePolling(load, done));
    await flush();
    visibility = "hidden";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    const asked = load.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(load).toHaveBeenCalledTimes(asked);
    visibility = "visible";
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(load).toHaveBeenCalledTimes(asked + 1);
  });

  it("keeps the last answer when a refresh fails, and keeps trying", async () => {
    const results: ApiResult<{ status: string }>[] = [
      ok("running"),
      { ok: false, failure: { kind: "unreachable", message: "No response from the API" } },
      ok("completed"),
    ];
    const load = vi.fn<Loader<{ status: string }>>(async () => results.shift() ?? ok("completed"));
    const { result } = renderHook(() => usePolling(load, done));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current[0]).toMatchObject({
      data: { status: "running" },
      refreshFailure: { kind: "unreachable" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current[0]).toMatchObject({
      data: { status: "completed" },
      refreshFailure: null,
    });
  });

  it("stops at a not-found answer and never asks after unmounting", async () => {
    const load = vi.fn<Loader<{ status: string }>>(async () => ({
      ok: false,
      failure: { kind: "not_found", code: "job_not_found", message: "x" },
    }));
    const { result, unmount } = renderHook(() => usePolling(load, done));
    await flush();
    expect(result.current[0]).toMatchObject({ status: "error" });
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(load).toHaveBeenCalledTimes(1);
  });
});
