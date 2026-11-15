import { describe, expect, it } from "vitest";
import {
  DEFAULT_FILTERS,
  assetRows,
  filterRows,
  readFilters,
  stateOptions,
  writeFilters,
} from "@/lib/assets/filter";
import { feeder } from "@/test/fixtures/networks";

const rows = assetRows(feeder());
const keys = (filters: Parameters<typeof filterRows>[1]) =>
  filterRows(rows, filters).map((r) => `${r.type}:${r.element.key}`);

describe("asset rows", () => {
  it("list every element, by type, in natural key order", () => {
    expect(rows).toHaveLength(14);
    expect(rows.slice(0, 4).map((r) => r.element.key)).toEqual(["a", "b", "c", "hv"]);
  });
});

describe("filters", () => {
  it("filter by type, state and text, alone and together", () => {
    expect(keys({ type: "lines", state: "any", query: "" })).toEqual([
      "lines:l-ab",
      "lines:l-bc",
      "lines:l-ca",
    ]);
    expect(keys({ type: "all", state: "out_of_service", query: "" })).toEqual([
      "buses:c",
      "lines:l-ca",
    ]);
    expect(keys({ type: "switches", state: "open", query: "" })).toEqual(["switches:s-bc"]);
    expect(keys({ type: "all", state: "closed", query: "" })).toEqual(["switches:s-ab"]);
    expect(keys({ type: "lines", state: "in_service", query: "bc" })).toEqual(["lines:l-bc"]);
    expect(keys({ type: "all", state: "any", query: "LOAD" })).toEqual([
      "loads:load-b",
      "loads:load-c",
    ]);
  });

  it("offer only the states that apply to the type", () => {
    expect(stateOptions("switches")).toEqual(["any", "open", "closed"]);
    expect(stateOptions("lines")).toEqual(["any", "in_service", "out_of_service"]);
    expect(stateOptions("all")).toHaveLength(5);
  });

  it("round-trip through the address, leaving defaults out and other parameters alone", () => {
    const filters = { type: "lines", state: "out_of_service", query: "6-7" } as const;
    const params = writeFilters(new URLSearchParams("element=lines%3Al1"), filters);
    expect(params.toString()).toBe("element=lines%3Al1&type=lines&state=out_of_service&q=6-7");
    expect(readFilters(params)).toEqual(filters);
    expect(writeFilters(params, DEFAULT_FILTERS).toString()).toBe("element=lines%3Al1");
  });

  it("ignore unknown values and states that do not apply", () => {
    expect(readFilters(new URLSearchParams("type=meters&state=broken"))).toEqual(DEFAULT_FILTERS);
    expect(readFilters(new URLSearchParams("type=switches&state=in_service")).state).toBe("any");
  });
});
