import { describe, expect, it } from "vitest";
import { decodeScenario, describeModification, modificationBody } from "@/lib/resources/scenarios";
import { fixtureScenario } from "@/test/fixtures/jobs";

describe("scenarios", () => {
  it("decode every kind of change", () => {
    const scenario = decodeScenario(fixtureScenario());
    expect(scenario?.specification.modifications).toEqual([
      { type: "scale_loads", factor: 1.2, keys: null },
      { type: "scale_generation", factor: 0, keys: ["pv-1"], controlMode: "constant_power" },
      { type: "set_in_service", elementType: "line", key: "l1", inService: false },
      { type: "set_switch", key: "s1", closed: true },
    ]);
  });

  it("refuse an unknown kind of change", () => {
    const payload = fixtureScenario({
      specification: {
        schema: "gridwise.scenario/1",
        modifications: [{ type: "trip", key: "s1" }],
      },
    });
    expect(decodeScenario(payload)).toBeNull();
  });

  it("send changes in the API's field names, leaving out what was not chosen", () => {
    const scenario = decodeScenario(fixtureScenario());
    expect(scenario?.specification.modifications.map(modificationBody)).toEqual(
      (fixtureScenario().specification as { modifications: unknown[] }).modifications,
    );
  });

  it("describe changes in words, with switches as model positions", () => {
    const scenario = decodeScenario(fixtureScenario());
    expect(scenario?.specification.modifications.map(describeModification)).toEqual([
      "Scale loads (all) by 1.2",
      "Scale generation (pv-1, constant power only) by 0",
      "Take line l1 out of service",
      "Set switch s1 to closed (model position)",
    ]);
  });
});
