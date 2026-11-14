import { describe, expect, it } from "vitest";
import { decodeGrid, decodeGridPage, totalElements } from "@/lib/resources/grids";
import { fixtureGrid, fixtureGridPage } from "@/test/fixtures/grids";

describe("grid decoders", () => {
  it("decode a grid as the API documents it", () => {
    const grid = decodeGrid(fixtureGrid());
    if (grid === null) throw new Error("fixture does not decode");
    expect(grid).toMatchObject({
      name: "Fixture feeder",
      dataOrigin: "synthetic",
      version: 3,
      frequencyHz: 50,
      elementCounts: { buses: 4, switches: 1 },
    });
    expect(totalElements(grid.elementCounts)).toBe(13);
  });

  it("decode a page of grids", () => {
    const page = decodeGridPage(fixtureGridPage([fixtureGrid()], 1));
    expect(page?.items).toHaveLength(1);
    expect(page?.total).toBe(1);
  });

  it.each([
    ["an unknown data origin", { data_origin: "measured" }],
    ["a missing origin", { data_origin: undefined }],
    ["a version as text", { version: "3" }],
    ["a fractional version", { version: 3.5 }],
    ["an id that is not a UUID", { id: "grid-1" }],
    ["a missing element count", { element_counts: { buses: 1 } }],
    ["a non-finite frequency", { frequency_hz: Number.POSITIVE_INFINITY }],
    ["a timestamp that is not one", { updated_at: "yesterday" }],
  ])("refuse %s", (_, overrides) => {
    expect(decodeGrid(fixtureGrid(overrides))).toBeNull();
  });

  it("refuse a page with one bad item", () => {
    const page = fixtureGridPage([fixtureGrid(), fixtureGrid({ name: 7 })]);
    expect(decodeGridPage(page)).toBeNull();
  });

  it("never catch errors that are not decoding errors", () => {
    const explode = {
      get id(): string {
        throw new RangeError("boom");
      },
    };
    expect(() => decodeGrid(explode)).toThrow(RangeError);
  });
});
