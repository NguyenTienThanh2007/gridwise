import { describe, expect, it, vi } from "vitest";
import type * as HttpClient from "@/lib/http/client";
import { request } from "@/lib/http/client";
import {
  decodeJob,
  decodeJobPage,
  isTerminal,
  submitSimulation,
} from "@/lib/resources/simulations";
import { FIXTURE_GRID_ID } from "@/test/fixtures/grids";
import { COMPLETED, FIXTURE_JOB_ID, fixtureJob } from "@/test/fixtures/jobs";

vi.mock("@/lib/http/client", async (original) => {
  const actual = await original<typeof HttpClient>();
  return { ...actual, request: vi.fn(actual.request) };
});

describe("job decoders", () => {
  it("decode a queued job and a completed one", () => {
    expect(decodeJob(fixtureJob())).toMatchObject({
      id: FIXTURE_JOB_ID,
      status: "queued",
      outcome: null,
      attempts: [],
    });
    expect(decodeJob(fixtureJob(COMPLETED))).toMatchObject({
      status: "completed",
      outcome: "converged",
      engine: { solverName: "pandapower" },
      attempts: [{ attempt: 1, endedBy: "completed" }],
    });
  });

  it("read list items, which have no attempts", () => {
    const item = fixtureJob();
    delete item.attempts;
    expect(
      decodeJobPage({ items: [item], total: 1, limit: 25, offset: 0 })?.items[0]?.attempts,
    ).toBeNull();
  });

  it.each([
    ["an unknown status", { status: "paused" }],
    ["an unknown outcome", { outcome: "partial" }],
    ["a missing source", { source: undefined }],
    [
      "iterations as text",
      {
        configuration: {
          algorithm: "newton_raphson",
          tolerance_mva: 1e-8,
          max_iterations: "10",
          hash: "x",
        },
      },
    ],
    ["a failure without a message", { failure: { code: "solver_failed" } }],
    [
      "an unknown source status",
      { source: { grid_id: null, grid_version: 1, topology_hash: "x", status: "moved" } },
    ],
  ])("refuse %s", (_, overrides) => {
    expect(decodeJob(fixtureJob(overrides))).toBeNull();
  });

  it("know which statuses are final", () => {
    expect(["queued", "running"].map((s) => isTerminal(s as never))).toEqual([false, false]);
    expect(["completed", "failed", "cancelled"].map((s) => isTerminal(s as never))).toEqual([
      true,
      true,
      true,
    ]);
  });
});

describe("submitSimulation", () => {
  it("sends the grid version as If-Match, the idempotency key, and only what was chosen", async () => {
    const mocked = vi.mocked(request);
    mocked.mockResolvedValueOnce({ ok: false, failure: { kind: "aborted" } });
    await submitSimulation({
      gridId: FIXTURE_GRID_ID,
      gridVersion: 3,
      scenarioId: null,
      configuration: { toleranceMva: 1e-6, maxIterations: 20 },
      idempotencyKey: "key-1",
    });
    const [path, , options] = mocked.mock.calls.at(-1) ?? [];
    expect(path).toBe(`/api/v1/grids/${FIXTURE_GRID_ID}/simulations`);
    expect(options).toMatchObject({
      method: "POST",
      ifMatch: 3,
      idempotencyKey: "key-1",
      body: { configuration: { tolerance_mva: 1e-6, max_iterations: 20 } },
    });
    expect(options?.body).not.toHaveProperty("scenario_id");
  });
});
