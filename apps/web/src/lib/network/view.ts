/** The visible part of the diagram, as an SVG view box. Pure helpers for fit, zoom and pan. */

import type { Bounds, Point } from "@/lib/network/layout";

export type View = Bounds;

/** Zoom limits relative to the whole drawing. */
const MIN_SCALE = 0.1;
const MAX_SCALE = 4;

export function fitView(bounds: Bounds): View {
  return { ...bounds };
}

export function zoomView(view: View, factor: number, bounds: Bounds): View {
  const width = Math.min(
    Math.max(view.width * factor, bounds.width * MIN_SCALE),
    bounds.width * MAX_SCALE,
  );
  const height = (view.height / view.width) * width;
  const cx = view.x + view.width / 2;
  const cy = view.y + view.height / 2;
  return { x: cx - width / 2, y: cy - height / 2, width, height };
}

export function centreOn(view: View, point: Point): View {
  return { ...view, x: point.x - view.width / 2, y: point.y - view.height / 2 };
}

export function panView(view: View, dx: number, dy: number): View {
  return { ...view, x: view.x - dx, y: view.y - dy };
}

export function contains(view: View, point: Point): boolean {
  return (
    point.x >= view.x &&
    point.x <= view.x + view.width &&
    point.y >= view.y &&
    point.y <= view.y + view.height
  );
}

export function viewBox(view: View): string {
  return [view.x, view.y, view.width, view.height].map((n) => Number(n.toFixed(2))).join(" ");
}
