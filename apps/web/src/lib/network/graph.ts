/**
 * How a stored network's elements refer to each other (decision 0014, section 10).
 *
 * Only relationships the topology states: a line or transformer joins two buses; a load,
 * generator or external grid sits at one bus; a switch sits at one bus, on a line or
 * transformer end or between two buses. Nothing here infers electrical state: no
 * energisation, no supply paths, whatever the switch positions are.
 */

import type { ElementType } from "@/lib/resources/grids";
import type {
  Bus,
  ExternalGrid,
  Generator,
  Line,
  Load,
  Network,
  Switch,
  Transformer,
} from "@/lib/resources/topology";
import type { ElementRef } from "@/lib/network/selection";

/** Natural order: `bus-2` before `bus-10`. Deterministic for any input order. */
export function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, "en", { numeric: true }) || (a < b ? -1 : a > b ? 1 : 0);
}

export type NetworkElement = Bus | Line | Transformer | Load | Generator | ExternalGrid | Switch;

const LISTS = {
  buses: "buses",
  lines: "lines",
  transformers: "transformers",
  loads: "loads",
  generators: "generators",
  external_grids: "externalGrids",
  switches: "switches",
} as const satisfies Record<ElementType, keyof Network>;

export function elementsOf(network: Network, type: ElementType): NetworkElement[] {
  return network[LISTS[type]];
}

export function findElement(network: Network, ref: ElementRef): NetworkElement | null {
  return elementsOf(network, ref.type).find((element) => element.key === ref.key) ?? null;
}

/** Something drawn between two buses: a line, a transformer or a bus-to-bus switch. */
export interface Connection {
  type: "lines" | "transformers" | "switches";
  key: string;
  fromBus: string;
  toBus: string;
}

/** Every connection, in a fixed order: lines, transformers, then bus couplers, each by key. */
export function connections(network: Network): Connection[] {
  const byKey = (a: Connection, b: Connection) => naturalCompare(a.key, b.key);
  return [
    ...network.lines
      .map((line): Connection => ({
        type: "lines",
        key: line.key,
        fromBus: line.fromBusKey,
        toBus: line.toBusKey,
      }))
      .sort(byKey),
    ...network.transformers
      .map((transformer): Connection => ({
        type: "transformers",
        key: transformer.key,
        fromBus: transformer.hvBusKey,
        toBus: transformer.lvBusKey,
      }))
      .sort(byKey),
    ...network.switches
      .filter((item) => item.elementType === "bus")
      .map((item): Connection => ({
        type: "switches",
        key: item.key,
        fromBus: item.busKey,
        toBus: item.elementKey,
      }))
      .sort(byKey),
  ];
}

export interface BrokenReference {
  element: ElementRef;
  field: string;
  target: string;
}

/**
 * References that point at nothing. The engine refuses such grids, so a stored grid has
 * none; if one ever arrives, the explorer draws nothing rather than guessing a connection.
 */
export function brokenReferences(network: Network): BrokenReference[] {
  const buses = new Set(network.buses.map((bus) => bus.key));
  const lines = new Map(network.lines.map((line) => [line.key, line]));
  const transformers = new Map(network.transformers.map((item) => [item.key, item]));
  const broken: BrokenReference[] = [];
  const check = (element: ElementRef, field: string, target: string) => {
    if (!buses.has(target)) broken.push({ element, field, target });
  };

  for (const line of network.lines) {
    check({ type: "lines", key: line.key }, "from_bus_key", line.fromBusKey);
    check({ type: "lines", key: line.key }, "to_bus_key", line.toBusKey);
  }
  for (const item of network.transformers) {
    check({ type: "transformers", key: item.key }, "hv_bus_key", item.hvBusKey);
    check({ type: "transformers", key: item.key }, "lv_bus_key", item.lvBusKey);
  }
  for (const item of network.loads) check({ type: "loads", key: item.key }, "bus_key", item.busKey);
  for (const item of network.generators) {
    check({ type: "generators", key: item.key }, "bus_key", item.busKey);
  }
  for (const item of network.externalGrids) {
    check({ type: "external_grids", key: item.key }, "bus_key", item.busKey);
  }
  for (const item of network.switches) {
    const ref: ElementRef = { type: "switches", key: item.key };
    check(ref, "bus_key", item.busKey);
    if (item.elementType === "bus") {
      check(ref, "element_key", item.elementKey);
      continue;
    }
    const target =
      item.elementType === "line" ? lines.get(item.elementKey) : transformers.get(item.elementKey);
    if (target === undefined) {
      broken.push({ element: ref, field: "element_key", target: item.elementKey });
      continue;
    }
    const ends =
      "fromBusKey" in target
        ? [target.fromBusKey, target.toBusKey]
        : [target.hvBusKey, target.lvBusKey];
    if (!ends.includes(item.busKey)) {
      // A switch on a line or transformer sits at one of its two ends.
      broken.push({ element: ref, field: "bus_key", target: item.busKey });
    }
  }
  return broken;
}

/** Everything the topology attaches to or connects at one bus, in a fixed order. */
export function elementsAtBus(network: Network, busKey: string): ElementRef[] {
  const refs: ElementRef[] = [];
  const add = (type: ElementType, keys: string[]) =>
    refs.push(...keys.sort(naturalCompare).map((key) => ({ type, key })));
  add(
    "lines",
    network.lines
      .filter((line) => line.fromBusKey === busKey || line.toBusKey === busKey)
      .map((line) => line.key),
  );
  add(
    "transformers",
    network.transformers
      .filter((item) => item.hvBusKey === busKey || item.lvBusKey === busKey)
      .map((item) => item.key),
  );
  add(
    "switches",
    network.switches
      .filter(
        (item) =>
          item.busKey === busKey || (item.elementType === "bus" && item.elementKey === busKey),
      )
      .map((item) => item.key),
  );
  add(
    "external_grids",
    network.externalGrids.filter((item) => item.busKey === busKey).map((item) => item.key),
  );
  add(
    "generators",
    network.generators.filter((item) => item.busKey === busKey).map((item) => item.key),
  );
  add(
    "loads",
    network.loads.filter((item) => item.busKey === busKey).map((item) => item.key),
  );
  return refs;
}
