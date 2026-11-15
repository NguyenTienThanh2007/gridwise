import { describe, expect, it } from "vitest";
import { brokenReferences, connections, elementsAtBus, naturalCompare } from "@/lib/network/graph";
import { bus, feeder, line, load, network, switchAt, transformer } from "@/test/fixtures/networks";

describe("connections", () => {
  it("are exactly the lines, transformers and bus couplers, in a fixed order", () => {
    const net = network({
      buses: [bus("a"), bus("b"), bus("c")],
      lines: [line("l-2", "a", "b"), line("l-10", "b", "c")],
      transformers: [transformer("t", "a", "c")],
      switches: [
        switchAt("coupler", "a", "bus", "c", true),
        switchAt("s", "a", "line", "l-2", true),
      ],
    });
    expect(connections(net).map((c) => [c.type, c.key, c.fromBus, c.toBus])).toEqual([
      ["lines", "l-2", "a", "b"],
      ["lines", "l-10", "b", "c"],
      ["transformers", "t", "a", "c"],
      ["switches", "coupler", "a", "c"],
    ]);
  });
});

describe("brokenReferences", () => {
  it("finds none in a consistent network", () => {
    expect(brokenReferences(feeder())).toEqual([]);
  });

  it("reports every reference to something that does not exist", () => {
    const net = network({
      buses: [bus("a"), bus("b")],
      lines: [line("l1", "a", "ghost")],
      loads: [load("x", "nowhere")],
      switches: [
        switchAt("s1", "a", "line", "no-line", true),
        switchAt("s2", "b", "line", "l1", true), // b is not an end of l1
        switchAt("s3", "a", "bus", "missing", false),
      ],
    });
    expect(brokenReferences(net)).toEqual([
      { element: { type: "lines", key: "l1" }, field: "to_bus_key", target: "ghost" },
      { element: { type: "loads", key: "x" }, field: "bus_key", target: "nowhere" },
      { element: { type: "switches", key: "s1" }, field: "element_key", target: "no-line" },
      { element: { type: "switches", key: "s2" }, field: "bus_key", target: "b" },
      { element: { type: "switches", key: "s3" }, field: "element_key", target: "missing" },
    ]);
  });
});

describe("elementsAtBus", () => {
  it("lists what the topology attaches to or connects at a bus", () => {
    expect(elementsAtBus(feeder(), "c")).toEqual([
      { type: "lines", key: "l-bc" },
      { type: "lines", key: "l-ca" },
      { type: "switches", key: "s-bc" },
      { type: "loads", key: "load-c" },
    ]);
  });
});

describe("naturalCompare", () => {
  it("orders numbered keys naturally", () => {
    expect(["bus-10", "bus-2", "bus-1"].sort(naturalCompare)).toEqual(["bus-1", "bus-2", "bus-10"]);
  });
});
