import { describe, expect, it } from "vitest";
import { formatElementRef, parseElementRef, sameRef } from "@/lib/network/selection";

describe("element references", () => {
  it("round-trip through the query parameter", () => {
    const ref = { type: "lines", key: "line-6-7" } as const;
    expect(parseElementRef(formatElementRef(ref))).toEqual(ref);
    expect(parseElementRef("switches:a:b")).toEqual({ type: "switches", key: "a:b" });
  });

  it.each([null, undefined, "", "lines", ":x", "lines:", "meters:m1"])("ignore %s", (value) => {
    expect(parseElementRef(value)).toBeNull();
  });

  it("compare by type and key", () => {
    expect(sameRef({ type: "buses", key: "a" }, { type: "buses", key: "a" })).toBe(true);
    expect(sameRef({ type: "buses", key: "a" }, { type: "loads", key: "a" })).toBe(false);
    expect(sameRef(null, null)).toBe(false);
  });
});
