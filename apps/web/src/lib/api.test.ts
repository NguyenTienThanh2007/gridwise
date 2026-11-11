import { describe, expect, it, vi } from "vitest";
import { fetchSystemStatus, parseReadiness } from "@/lib/api";

const READY = {
  status: "ready",
  database: "ok",
  schema_revision: "0001",
  expected_schema_revision: "0001",
};
const INFO = {
  name: "gridwise-api",
  version: "0.1.0",
  environment: "test",
  operating_mode: "simulation_and_decision_support",
  notice: "Decision support only.",
};

function respond(routes: Record<string, { status: number; body: unknown }>): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL) => {
    const route = routes[new URL(String(input)).pathname];
    if (route === undefined) throw new Error("unexpected request");
    return new Response(JSON.stringify(route.body), { status: route.status });
  }) as unknown as typeof fetch;
}

describe("fetchSystemStatus", () => {
  it("reports ready with system info", async () => {
    const status = await fetchSystemStatus(
      respond({
        "/health/ready": { status: 200, body: READY },
        "/api/v1/system/info": { status: 200, body: INFO },
      }),
      "http://api.test",
    );
    expect(status).toMatchObject({ kind: "ready", info: { version: "0.1.0" } });
  });

  it("treats 503 as an answer, not an outage", async () => {
    const body = {
      status: "not_ready",
      database: "unavailable",
      schema_revision: null,
      expected_schema_revision: "0001",
    };
    const status = await fetchSystemStatus(
      respond({ "/health/ready": { status: 503, body } }),
      "http://api.test",
    );
    expect(status).toEqual({ kind: "not_ready", readiness: body });
  });

  it("reports unreachable when the request fails", async () => {
    const failing = vi.fn(async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    expect(await fetchSystemStatus(failing, "http://api.test")).toEqual({
      kind: "unreachable",
      reason: "No response from the API",
    });
  });

  it("does not trust an unrecognised payload", async () => {
    const status = await fetchSystemStatus(
      respond({ "/health/ready": { status: 200, body: { status: "fine" } } }),
      "http://api.test",
    );
    expect(status.kind).toBe("unreachable");
  });

  it("reports unreachable on an unexpected status code", async () => {
    const status = await fetchSystemStatus(
      respond({ "/health/ready": { status: 500, body: {} } }),
      "http://api.test",
    );
    expect(status).toEqual({ kind: "unreachable", reason: "Unexpected HTTP 500" });
  });
});

/** Accepts the request and never answers; only the abort signal can end it. */
const neverResponds = ((_input: RequestInfo | URL, init?: RequestInit) =>
  new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
  })) as typeof fetch;

describe("fetchSystemStatus timeout", () => {
  it("gives up on an API that never responds", async () => {
    const started = Date.now();
    const status = await fetchSystemStatus(neverResponds, "http://api.test", 50);
    expect(status).toEqual({ kind: "unreachable", reason: "No response within 0.1 seconds" });
    expect(Date.now() - started).toBeLessThan(2_000);
  });

  it("applies one deadline to the whole check, including a stalled second request", async () => {
    const stallsOnInfo = ((input: RequestInfo | URL, init?: RequestInit) =>
      new URL(String(input)).pathname === "/health/ready"
        ? Promise.resolve(new Response(JSON.stringify(READY), { status: 200 }))
        : neverResponds(input, init)) as typeof fetch;
    const status = await fetchSystemStatus(stallsOnInfo, "http://api.test", 50);
    expect(status.kind).toBe("unreachable");
  });

  it("passes an abort signal with every request", async () => {
    const fetchSpy = respond({
      "/health/ready": { status: 200, body: READY },
      "/api/v1/system/info": { status: 200, body: INFO },
    });
    await fetchSystemStatus(fetchSpy, "http://api.test");
    const calls = vi.mocked(fetchSpy).mock.calls;
    expect(calls).toHaveLength(2);
    for (const [, init] of calls) expect(init?.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("schema mismatch", () => {
  it("is reported as not ready with both revisions", async () => {
    const body = {
      status: "not_ready",
      database: "schema_mismatch",
      schema_revision: "0001",
      expected_schema_revision: "0002",
    };
    const status = await fetchSystemStatus(
      respond({ "/health/ready": { status: 503, body } }),
      "http://api.test",
    );
    expect(status).toEqual({ kind: "not_ready", readiness: body });
  });
});

describe("parseReadiness", () => {
  it.each([null, "ready", [], { status: "ready" }, { ...READY, database: "great" }])(
    "rejects %j",
    (value) => {
      expect(parseReadiness(value)).toBeNull();
    },
  );
});
