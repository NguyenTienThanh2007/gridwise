/**
 * Where each element of a stored network is drawn (decision 0014, section 10). Pure and
 * deterministic: the same network gives the same drawing, whatever the order of its lists.
 *
 * Buses use their stored diagram positions when every bus has one (y grows upwards in the
 * data and downwards in SVG, so it is flipped). Otherwise every bus is placed by a layered
 * layout of the network's connections: mixing stored and computed positions would look
 * arbitrary. Positions are drawing positions, not geography.
 *
 * Connections are drawn whatever their service state or switch position, so the drawing
 * does not move when a switch changes. Nothing here works out what is energised.
 */

import { type Connection, connections, naturalCompare } from "@/lib/network/graph";
import type { Network } from "@/lib/resources/topology";

/** The shortest distance between two buses, in SVG units. */
export const UNIT = 80;
/** Distance between parallel connections joining the same two buses. */
export const PARALLEL_OFFSET = 22;
/** Attached elements drawn per type at one bus; the rest are counted in a "+n" badge. */
export const MAX_GLYPHS = 4;
const GLYPH_DISTANCE = 30;
const GLYPH_SPACING = 18;
const MARGIN = 48;

export interface Point {
  x: number;
  y: number;
}

export interface ConnectionShape extends Connection {
  from: Point;
  to: Point;
  /** Control point of a quadratic curve, for parallel connections; null when straight. */
  control: Point | null;
  mid: Point;
}

/** A switch on a line or transformer, drawn on that element near its own bus. */
export interface SwitchMarker {
  key: string;
  at: Point;
}

export type GlyphType = "loads" | "generators" | "external_grids";

export interface Glyph {
  type: GlyphType;
  key: string;
  busKey: string;
  at: Point;
}

export interface Overflow {
  type: GlyphType;
  busKey: string;
  count: number;
  at: Point;
}

export interface Bounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Layout {
  source: "stored" | "fallback";
  /** Buses without a stored diagram position. */
  missingPositions: number;
  buses: Map<string, Point>;
  connections: ConnectionShape[];
  switchMarkers: SwitchMarker[];
  glyphs: Glyph[];
  overflows: Overflow[];
  bounds: Bounds;
}

// --- bus positions --------------------------------------------------------------------------

function minimumDistance(points: Point[]): number {
  let best = Number.POSITIVE_INFINITY;
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      const a = points[i] as Point;
      const b = points[j] as Point;
      const distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (distance > 0 && distance < best) best = distance;
    }
  }
  return best;
}

function storedPositions(network: Network): Map<string, Point> {
  const raw = network.buses.map((bus) => ({ key: bus.key, point: bus.diagram as Point }));
  const points = raw.map((item) => item.point);
  const minX = Math.min(...points.map((point) => point.x));
  const maxY = Math.max(...points.map((point) => point.y));
  // Exact for ordinary grids; for very large ones the spacing comes from the area.
  const spacing =
    points.length <= 2000
      ? minimumDistance(points)
      : Math.sqrt(
          ((Math.max(...points.map((p) => p.x)) - minX || 1) *
            (maxY - Math.min(...points.map((p) => p.y)) || 1)) /
            points.length,
        );
  const scale = Number.isFinite(spacing) && spacing > 0 ? UNIT / spacing : UNIT;
  return new Map(
    raw.map(({ key, point }) => [
      key,
      { x: (point.x - minX) * scale, y: (maxY - point.y) * scale },
    ]),
  );
}

/** Layered layout: each connected part from its external-grid buses, breadth first. */
export function fallbackPositions(network: Network): Map<string, Point> {
  const keys = network.buses.map((bus) => bus.key).sort(naturalCompare);
  const neighbours = new Map<string, Set<string>>(keys.map((key) => [key, new Set()]));
  for (const connection of connections(network)) {
    if (connection.fromBus === connection.toBus) continue;
    neighbours.get(connection.fromBus)?.add(connection.toBus);
    neighbours.get(connection.toBus)?.add(connection.fromBus);
  }
  const sortedNeighbours = (key: string) => [...(neighbours.get(key) ?? [])].sort(naturalCompare);
  const supplied = new Set(network.externalGrids.map((item) => item.busKey));

  // Connected parts, each listed by key.
  const seen = new Set<string>();
  const parts: string[][] = [];
  for (const start of keys) {
    if (seen.has(start)) continue;
    const part: string[] = [];
    const stack = [start];
    seen.add(start);
    while (stack.length > 0) {
      const key = stack.pop() as string;
      part.push(key);
      for (const next of sortedNeighbours(key)) {
        if (!seen.has(next)) {
          seen.add(next);
          stack.push(next);
        }
      }
    }
    parts.push(part.sort(naturalCompare));
  }
  parts.sort((a, b) => {
    const supplyA = a.some((key) => supplied.has(key)) ? 0 : 1;
    const supplyB = b.some((key) => supplied.has(key)) ? 0 : 1;
    return supplyA - supplyB || naturalCompare(a[0] as string, b[0] as string);
  });

  const positions = new Map<string, Point>();
  let offset = 0;
  for (const part of parts) {
    const roots = part.filter((key) => supplied.has(key));
    const layers: string[][] = [roots.length > 0 ? roots : [part[0] as string]];
    const placed = new Set(layers[0]);
    const order = new Map<string, number>(layers[0]?.map((key, index) => [key, index]));
    while (true) {
      const previous = layers[layers.length - 1] as string[];
      const next: { key: string; parent: number }[] = [];
      for (const parent of previous) {
        for (const key of sortedNeighbours(parent)) {
          if (!placed.has(key)) {
            placed.add(key);
            next.push({ key, parent: order.get(parent) ?? 0 });
          }
        }
      }
      if (next.length === 0) break;
      next.sort((a, b) => a.parent - b.parent || naturalCompare(a.key, b.key));
      const layer = next.map((item) => item.key);
      layer.forEach((key, index) => order.set(key, index));
      layers.push(layer);
    }
    const width = Math.max(...layers.map((layer) => layer.length));
    layers.forEach((layer, depth) => {
      layer.forEach((key, index) => {
        positions.set(key, {
          x: (offset + (width - layer.length) / 2 + index) * UNIT,
          y: depth * UNIT,
        });
      });
    });
    offset += width + 1;
  }
  return positions;
}

// --- shapes ---------------------------------------------------------------------------------

function pointOn(shape: { from: Point; to: Point; control: Point | null }, t: number): Point {
  const { from, to, control } = shape;
  if (control === null) {
    return { x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t };
  }
  const u = 1 - t;
  return {
    x: u * u * from.x + 2 * u * t * control.x + t * t * to.x,
    y: u * u * from.y + 2 * u * t * control.y + t * t * to.y,
  };
}

function connectionShapes(network: Network, buses: Map<string, Point>): ConnectionShape[] {
  const all = connections(network);
  const groups = new Map<string, Connection[]>();
  for (const connection of all) {
    const pair = [connection.fromBus, connection.toBus].sort(naturalCompare).join("\u0000");
    groups.set(pair, [...(groups.get(pair) ?? []), connection]);
  }
  return all.map((connection) => {
    const from = buses.get(connection.fromBus) as Point;
    const to = buses.get(connection.toBus) as Point;
    const pair = [connection.fromBus, connection.toBus].sort(naturalCompare).join("\u0000");
    const group = groups.get(pair) as Connection[];
    let control: Point | null = null;
    if (group.length > 1) {
      const index = group.indexOf(connection);
      // The normal of the pair's own direction (from its first bus in natural order), so
      // parallel connections fan out the same way whichever way each one is stored.
      const [first] = [connection.fromBus, connection.toBus].sort(naturalCompare);
      const a = first === connection.fromBus ? from : to;
      const b = first === connection.fromBus ? to : from;
      const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
      const normal = { x: -(b.y - a.y) / length, y: (b.x - a.x) / length };
      const shift = (index - (group.length - 1) / 2) * PARALLEL_OFFSET * 2;
      control = {
        x: (from.x + to.x) / 2 + normal.x * shift,
        y: (from.y + to.y) / 2 + normal.y * shift,
      };
    }
    const shape = { ...connection, from, to, control };
    return { ...shape, mid: pointOn(shape, 0.5) };
  });
}

function switchMarkers(network: Network, shapes: ConnectionShape[]): SwitchMarker[] {
  const byElement = new Map(shapes.map((shape) => [`${shape.type}:${shape.key}`, shape]));
  return network.switches
    .filter((item) => item.elementType !== "bus")
    .sort((a, b) => naturalCompare(a.key, b.key))
    .flatMap((item) => {
      const type = item.elementType === "line" ? "lines" : "transformers";
      const shape = byElement.get(`${type}:${item.elementKey}`);
      if (shape === undefined) return [];
      // A quarter of the way along the element, from the bus the switch sits at.
      const t = item.busKey === shape.fromBus ? 0.25 : 0.75;
      return [{ key: item.key, at: pointOn(shape, t) }];
    });
}

const GLYPH_DIRECTIONS: Record<GlyphType, Point> = {
  external_grids: { x: 0, y: -1 },
  generators: { x: Math.SQRT1_2, y: -Math.SQRT1_2 },
  loads: { x: 0, y: 1 },
};

function glyphs(network: Network, buses: Map<string, Point>): Pick<Layout, "glyphs" | "overflows"> {
  const placed: Glyph[] = [];
  const overflows: Overflow[] = [];
  const groups: [GlyphType, { key: string; busKey: string }[]][] = [
    ["external_grids", network.externalGrids],
    ["generators", network.generators],
    ["loads", network.loads],
  ];
  for (const [type, items] of groups) {
    const byBus = new Map<string, string[]>();
    for (const item of items) byBus.set(item.busKey, [...(byBus.get(item.busKey) ?? []), item.key]);
    for (const busKey of [...byBus.keys()].sort(naturalCompare)) {
      const bus = buses.get(busKey);
      if (bus === undefined) continue;
      const keys = (byBus.get(busKey) as string[]).sort(naturalCompare);
      const shown = keys.slice(0, MAX_GLYPHS);
      const slots = shown.length + (keys.length > MAX_GLYPHS ? 1 : 0);
      const direction = GLYPH_DIRECTIONS[type];
      const across = { x: -direction.y, y: direction.x };
      const at = (slot: number): Point => {
        const spread = (slot - (slots - 1) / 2) * GLYPH_SPACING;
        return {
          x: bus.x + direction.x * GLYPH_DISTANCE + across.x * spread,
          y: bus.y + direction.y * GLYPH_DISTANCE + across.y * spread,
        };
      };
      shown.forEach((key, slot) => placed.push({ type, key, busKey, at: at(slot) }));
      if (keys.length > MAX_GLYPHS) {
        overflows.push({ type, busKey, count: keys.length - MAX_GLYPHS, at: at(shown.length) });
      }
    }
  }
  return { glyphs: placed, overflows };
}

function boundsOf(points: Point[]): Bounds {
  if (points.length === 0) return { x: -MARGIN, y: -MARGIN, width: 2 * MARGIN, height: 2 * MARGIN };
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs) - MARGIN;
  const minY = Math.min(...ys) - MARGIN;
  return {
    x: minX,
    y: minY,
    width: Math.max(...xs) + MARGIN - minX,
    height: Math.max(...ys) + MARGIN - minY,
  };
}

/** The whole drawing. Call only for a network without broken references (graph.ts). */
export function layoutNetwork(network: Network): Layout {
  const missingPositions = network.buses.filter((bus) => bus.diagram === null).length;
  const source = network.buses.length > 0 && missingPositions === 0 ? "stored" : "fallback";
  const buses = source === "stored" ? storedPositions(network) : fallbackPositions(network);
  const shapes = connectionShapes(network, buses);
  const attached = glyphs(network, buses);
  return {
    source,
    missingPositions,
    buses,
    connections: shapes,
    switchMarkers: switchMarkers(network, shapes),
    ...attached,
    bounds: boundsOf([
      ...buses.values(),
      ...shapes.flatMap((shape) => (shape.control === null ? [] : [shape.mid])),
      ...attached.glyphs.map((glyph) => glyph.at),
      ...attached.overflows.map((overflow) => overflow.at),
    ]),
  };
}
