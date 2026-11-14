import { describe, expect, it } from "vitest";
import { decodeTopology } from "@/lib/resources/topology";
import { fixtureTopology } from "@/test/fixtures/grids";

type Network = Record<string, unknown>;

/** The fixture with one change to its network. */
function changed(change: (network: Network) => void): Record<string, unknown> {
  const payload = fixtureTopology();
  change(payload.topology as Network);
  return payload;
}

/** The first element of one list in the network, for changing a field of it. */
function first(network: Network, name: string): Record<string, unknown> {
  const items = network[name] as Record<string, unknown>[];
  const item = items[0];
  if (item === undefined) throw new Error(`fixture has no ${name}`);
  return item;
}

describe("decodeTopology", () => {
  it("decodes every element type with its documented fields", () => {
    const topology = decodeTopology(fixtureTopology());
    if (topology === null) throw new Error("fixture does not decode");
    const network = topology.network;
    expect(network.buses.map((bus) => bus.diagram)).toEqual([{ x: 0, y: 2 }, null]);
    expect(network.transformers[0]?.tap?.position).toBe(0);
    expect(network.generators[0]?.voltageSetpointPu).toBeNull();
    expect(network.switches[0]).toMatchObject({ closed: false, elementType: "line" });
    expect(network.externalGrids[0]?.busKey).toBe("hv");
    expect(topology.dataOrigin).toBe("synthetic");
  });

  it.each<[string, (network: Network) => void]>([
    ["a switch position as text", (n) => (first(n, "switches").closed = "false")],
    ["an unknown switch kind", (n) => (first(n, "switches").kind = "breaker")],
    ["a missing list", (n) => delete n.loads],
    ["a load without power", (n) => (first(n, "loads").p_mw = null)],
    ["an unknown control mode", (n) => (first(n, "generators").control_mode = "droop")],
  ])("refuses %s", (_, change) => {
    expect(decodeTopology(changed(change))).toBeNull();
  });
});
