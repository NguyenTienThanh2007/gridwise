import { describe, expect, it } from "vitest";
import { MAX_GLYPHS, UNIT, fallbackPositions, layoutNetwork } from "@/lib/network/layout";
import type { Network } from "@/lib/resources/topology";
import { bus, externalGrid, feeder, line, load, network, switchAt } from "@/test/fixtures/networks";

function reversed(net: Network): Network {
  return {
    ...net,
    buses: [...net.buses].reverse(),
    lines: [...net.lines].reverse(),
    transformers: [...net.transformers].reverse(),
    loads: [...net.loads].reverse(),
    generators: [...net.generators].reverse(),
    externalGrids: [...net.externalGrids].reverse(),
    switches: [...net.switches].reverse(),
  };
}

describe("stored positions", () => {
  it("are used when every bus has one, flipped so that y grows downwards, and scaled", () => {
    const layout = layoutNetwork(feeder());
    expect(layout.source).toBe("stored");
    expect(layout.missingPositions).toBe(0);
    // Stored: hv (0,4) a (0,2) b (2,2) c (2,0); the closest buses are 2 apart.
    const scale = UNIT / 2;
    expect(layout.buses.get("hv")).toEqual({ x: 0, y: 0 });
    expect(layout.buses.get("a")).toEqual({ x: 0, y: 2 * scale });
    expect(layout.buses.get("c")).toEqual({ x: 2 * scale, y: 4 * scale });
  });

  it("are not mixed with computed ones: one bus without a position means none are used", () => {
    const net = feeder();
    const partial = {
      ...net,
      buses: net.buses.map((b, i) => (i === 1 ? { ...b, diagram: null } : b)),
    };
    const layout = layoutNetwork(partial);
    expect(layout.source).toBe("fallback");
    expect(layout.missingPositions).toBe(1);
    expect(layout.buses).toEqual(fallbackPositions(partial));
  });
});

describe("fallback layout", () => {
  const unplaced = (net: Network): Network => ({
    ...net,
    buses: net.buses.map((b) => ({ ...b, diagram: null })),
  });

  it("starts at the external-grid bus and places buses by depth", () => {
    const positions = fallbackPositions(unplaced(feeder()));
    expect(positions.get("hv")?.y).toBe(0);
    expect(positions.get("a")?.y).toBe(UNIT);
    // b and c are both one step from a (through l-ab and the ring line l-ca).
    expect(positions.get("b")?.y).toBe(2 * UNIT);
    expect(positions.get("c")?.y).toBe(2 * UNIT);
    expect(positions.get("b")?.x).toBeLessThan(positions.get("c")?.x ?? 0);
  });

  it("is the same whatever order the lists come in", () => {
    const net = unplaced(feeder());
    expect(layoutNetwork(reversed(net))).toEqual(layoutNetwork(net));
  });

  it("puts separate parts side by side, the supplied part first, without overlap", () => {
    const net = network({
      buses: [bus("z1"), bus("z2"), bus("a1"), bus("a2"), bus("lonely")],
      lines: [line("l-z", "z1", "z2"), line("l-a", "a1", "a2")],
      externalGrids: [externalGrid("ext", "z1")],
    });
    const positions = fallbackPositions(net);
    expect(positions.get("z1")).toEqual({ x: 0, y: 0 });
    expect(positions.get("a1")).toEqual({ x: 2 * UNIT, y: 0 });
    expect(positions.get("lonely")).toEqual({ x: 4 * UNIT, y: 0 });
    const points = [...positions.values()].map((p) => `${p.x},${p.y}`);
    expect(new Set(points).size).toBe(points.length);
  });

  it("is used for every bus when no bus has a position", () => {
    const layout = layoutNetwork(unplaced(feeder()));
    expect(layout.source).toBe("fallback");
    expect(layout.missingPositions).toBe(4);
  });
});

describe("connections and markers", () => {
  it("draw one connection per line, transformer and bus coupler between its own buses", () => {
    const layout = layoutNetwork(feeder());
    expect(layout.connections.map((c) => `${c.type}:${c.key}:${c.fromBus}-${c.toBus}`)).toEqual([
      "lines:l-ab:a-b",
      "lines:l-bc:b-c",
      "lines:l-ca:c-a",
      "transformers:t1:hv-a",
    ]);
    for (const shape of layout.connections) {
      expect(shape.from).toEqual(layout.buses.get(shape.fromBus));
      expect(shape.to).toEqual(layout.buses.get(shape.toBus));
    }
  });

  it("separate parallel connections between the same two buses", () => {
    const net = network({
      buses: [bus("a", { x: 0, y: 0 }), bus("b", { x: 2, y: 0 })],
      lines: [line("l1", "a", "b"), line("l2", "b", "a"), line("l3", "a", "b")],
    });
    const shapes = layoutNetwork(net).connections;
    expect(shapes.every((shape) => shape.control !== null)).toBe(true);
    const mids = shapes.map((shape) => Math.round(shape.mid.y));
    expect(new Set(mids).size).toBe(3);
    expect(
      layoutNetwork(network({ ...net, lines: [line("l1", "a", "b")] })).connections[0]?.control,
    ).toBeNull();
  });

  it("put a switch on its element, near the bus it sits at", () => {
    const layout = layoutNetwork(feeder());
    const b = layout.buses.get("b");
    const c = layout.buses.get("c");
    const marker = layout.switchMarkers.find((m) => m.key === "s-bc");
    // s-bc sits at c on l-bc (b → c): three quarters of the way from b.
    expect(marker?.at).toEqual({
      x: (b?.x ?? 0) + ((c?.x ?? 0) - (b?.x ?? 0)) * 0.75,
      y: (b?.y ?? 0) + ((c?.y ?? 0) - (b?.y ?? 0)) * 0.75,
    });
    const s = layout.switchMarkers.find((m) => m.key === "s-ab");
    const a = layout.buses.get("a");
    expect(s?.at.x).toBeCloseTo((a?.x ?? 0) + ((b?.x ?? 0) - (a?.x ?? 0)) * 0.25);
  });

  it("draw a bus coupler as a connection, not as a marker", () => {
    const net = network({
      buses: [bus("a", { x: 0, y: 0 }), bus("b", { x: 1, y: 0 })],
      switches: [switchAt("coupler", "a", "bus", "b", false)],
    });
    const layout = layoutNetwork(net);
    expect(layout.connections.map((c) => c.key)).toEqual(["coupler"]);
    expect(layout.switchMarkers).toEqual([]);
  });
});

describe("attached elements", () => {
  it("are drawn next to their own bus, and counted beyond the limit", () => {
    const loads = Array.from({ length: MAX_GLYPHS + 2 }, (_, i) => load(`load-${i + 1}`, "a"));
    const net = network({ buses: [bus("a", { x: 0, y: 0 })], loads });
    const layout = layoutNetwork(net);
    expect(layout.glyphs.map((glyph) => glyph.key)).toEqual([
      "load-1",
      "load-2",
      "load-3",
      "load-4",
    ]);
    expect(layout.glyphs.every((glyph) => glyph.busKey === "a" && glyph.at.y > 0)).toBe(true);
    expect(layout.overflows).toEqual([
      expect.objectContaining({ busKey: "a", count: 2, type: "loads" }),
    ]);
  });

  it("are inside the bounds", () => {
    const layout = layoutNetwork(feeder());
    for (const glyph of layout.glyphs) {
      expect(glyph.at.x).toBeGreaterThan(layout.bounds.x);
      expect(glyph.at.y).toBeGreaterThan(layout.bounds.y);
      expect(glyph.at.x).toBeLessThan(layout.bounds.x + layout.bounds.width);
      expect(glyph.at.y).toBeLessThan(layout.bounds.y + layout.bounds.height);
    }
  });
});
