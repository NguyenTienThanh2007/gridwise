import { describe, expect, it, vi } from "vitest";
import { noContent, request, versionFromEtag } from "@/lib/http/client";

const BASE = "http://api.test";

function answer(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchImpl = vi.fn(
    async () => new Response(body === undefined ? null : JSON.stringify(body), { status, headers }),
  );
  return fetchImpl as unknown as typeof fetch & typeof fetchImpl;
}

const asText = (value: unknown) => (typeof value === "string" ? value : null);

function error(code: string, extra: Record<string, unknown> = {}) {
  return { error: { code, message: `message for ${code}`, request_id: "req-1", ...extra } };
}

describe("request", () => {
  it("returns decoded data with the version from the ETag and the Location", async () => {
    const fetchImpl = answer(201, "hello", { ETag: '"7"', Location: "/api/v1/x/1" });
    const result = await request("/x", asText, { fetchImpl, baseUrl: BASE });
    expect(result).toMatchObject({ ok: true, data: "hello", etag: 7, location: "/api/v1/x/1" });
  });

  it("sends JSON, If-Match as a strong ETag and the Idempotency-Key", async () => {
    const fetchImpl = answer(200, "ok");
    await request("/x", asText, {
      method: "PATCH",
      body: { closed: true },
      ifMatch: 4,
      idempotencyKey: "key-1",
      fetchImpl,
      baseUrl: BASE,
    });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/x");
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe('{"closed":true}');
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      "If-Match": '"4"',
      "Idempotency-Key": "key-1",
    });
  });

  it("refuses a body of the wrong shape instead of guessing", async () => {
    const result = await request("/x", asText, { fetchImpl: answer(200, 42), baseUrl: BASE });
    expect(result).toEqual({
      ok: false,
      failure: {
        kind: "unexpected",
        status: 200,
        message: "The API answered with data in an unrecognised shape",
      },
    });
  });

  it("decodes an empty 204", async () => {
    const result = await request("/x", noContent, {
      fetchImpl: answer(204, undefined),
      baseUrl: BASE,
    });
    expect(result).toMatchObject({ ok: true, data: true });
  });

  it.each([
    [404, error("not_found"), { kind: "not_available" }],
    [404, undefined, { kind: "not_available" }],
    [503, error("development_tenant_not_configured"), { kind: "no_tenant" }],
    [404, error("grid_not_found"), { kind: "not_found", code: "grid_not_found" }],
    [409, error("grid_name_conflict"), { kind: "conflict", status: 409, currentVersion: null }],
    [
      422,
      error("scenario_invalid", {
        details: [
          { location: ["body", "modifications", 0], message: "m", type: "invalid_scale_factor" },
        ],
      }),
      { kind: "invalid", status: 422, details: [{ type: "invalid_scale_factor" }] },
    ],
    [428, error("precondition_required"), { kind: "invalid", status: 428 }],
    [500, error("internal_error"), { kind: "server", requestId: "req-1" }],
    [502, undefined, { kind: "server", requestId: null }],
    [418, error("teapot"), { kind: "unexpected", status: 418 }],
    [400, { not: "an error body" }, { kind: "unexpected", status: 400 }],
  ])("maps HTTP %i to its failure kind", async (status, body, expected) => {
    const result = await request("/x", asText, { fetchImpl: answer(status, body), baseUrl: BASE });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.failure).toMatchObject(expected);
  });

  it("reports the grid's current version on a 412", async () => {
    const result = await request("/x", asText, {
      fetchImpl: answer(412, error("version_conflict"), { ETag: '"9"' }),
      baseUrl: BASE,
    });
    expect(result).toMatchObject({
      ok: false,
      failure: { kind: "conflict", status: 412, code: "version_conflict", currentVersion: 9 },
    });
  });

  it("reports a network failure as unreachable", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const result = await request("/x", asText, { fetchImpl, baseUrl: BASE });
    expect(result).toEqual({
      ok: false,
      failure: { kind: "unreachable", message: "No response from the API" },
    });
  });

  it("gives up after the deadline", async () => {
    const fetchImpl = vi.fn(
      (_: unknown, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
        }),
    ) as unknown as typeof fetch;
    const result = await request("/x", asText, { fetchImpl, baseUrl: BASE, timeoutMs: 20 });
    expect(result).toEqual({
      ok: false,
      failure: { kind: "unreachable", message: "No response within 0 seconds" },
    });
  });

  it("reports a request the caller cancelled as aborted", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn(
      (_: unknown, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
        }),
    ) as unknown as typeof fetch;
    const pending = request("/x", asText, { fetchImpl, baseUrl: BASE, signal: controller.signal });
    controller.abort();
    expect(await pending).toEqual({ ok: false, failure: { kind: "aborted" } });
  });
});

describe("versionFromEtag", () => {
  it.each([
    ['"3"', 3],
    ['W/"3"', null],
    ['"0"', null],
    ["3", null],
    [null, null],
  ])("reads %s as %s", (value, expected) => {
    expect(versionFromEtag(value)).toBe(expected);
  });
});
