import { describe, expect, it, vi } from "vitest";
import {
  NAME_MAX,
  assetChangeBody,
  decodeAssetResponse,
  descriptionError,
  nameError,
} from "@/lib/resources/assets";
import { request } from "@/lib/http/client";
import { FIXTURE_GRID_ID, fixtureTopology } from "@/test/fixtures/grids";

function response(type: string, asset: unknown) {
  return { grid_id: FIXTURE_GRID_ID, grid_version: 4, topology_hash: "cd".repeat(32), type, asset };
}

const network = fixtureTopology().topology as Record<string, Record<string, unknown>[]>;
const first = (name: string) => network[name]?.[0] as Record<string, unknown>;

describe("decodeAssetResponse", () => {
  it("reads the asset with the reader of the type the response states", () => {
    expect(decodeAssetResponse(response("switches", first("switches")))).toMatchObject({
      gridVersion: 4,
      type: "switches",
      asset: { key: "s1", closed: false },
    });
    expect(decodeAssetResponse(response("lines", first("lines")))?.asset).toMatchObject({
      key: "l1",
      inService: true,
    });
  });

  it.each([
    ["a type that does not match the asset", response("switches", first("lines"))],
    ["an unknown type", response("meters", first("lines"))],
    ["a version as text", { ...response("lines", first("lines")), grid_version: "4" }],
    ["a missing asset", response("lines", undefined)],
  ])("refuses %s", (_, payload) => {
    expect(decodeAssetResponse(payload)).toBeNull();
  });
});

describe("assetChangeBody", () => {
  it("sends only what the API accepts for each kind of element", () => {
    expect(assetChangeBody({ kind: "switch", closed: true })).toEqual({ closed: true });
    expect(assetChangeBody({ kind: "element", name: "L", inService: false })).toEqual({
      name: "L",
      in_service: false,
    });
    expect(assetChangeBody({ kind: "element" })).toEqual({});
  });
});

describe("a write", () => {
  it("sends If-Match with the version the user saw, and reports the current one on 412", async () => {
    const fetchImpl = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            error: { code: "version_conflict", message: "changed", request_id: null },
          }),
          { status: 412, headers: { ETag: '"7"' } },
        ),
    );
    const result = await request("/api/v1/grids/x/assets/lines/l1", decodeAssetResponse, {
      method: "PATCH",
      body: assetChangeBody({ kind: "element", inService: false }),
      ifMatch: 5,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      baseUrl: "http://api.test",
    });
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.headers).toMatchObject({ "If-Match": '"5"' });
    expect(result).toMatchObject({
      ok: false,
      failure: { kind: "conflict", status: 412, currentVersion: 7 },
    });
  });
});

describe("field rules", () => {
  it("mirror the API's name and description limits", () => {
    expect(nameError("Feeder")).toBeNull();
    expect(nameError("")).toBe("Enter a name.");
    expect(nameError("   ")).toBe("Enter a name.");
    expect(nameError("x".repeat(NAME_MAX))).toBeNull();
    expect(nameError("x".repeat(NAME_MAX + 1))).toBe("Use at most 200 characters.");
    expect(descriptionError("")).toBeNull();
    expect(descriptionError("x".repeat(2001))).toBe("Use at most 2000 characters.");
  });
});
