"use client";

import { type PointerEvent, useRef } from "react";
import type { Glyph, Layout, Point } from "@/lib/network/layout";
import { type ElementRef, formatElementRef, sameRef } from "@/lib/network/selection";
import { type View, panView, viewBox } from "@/lib/network/view";
import type { Network } from "@/lib/resources/topology";

/** Above this many buses the diagram drops its labels; the list and inspector keep them. */
export const LABEL_LIMIT = 300;

const MUTED = "stroke-muted";
const DASH = "5 4";

interface Props {
  network: Network;
  layout: Layout;
  view: View;
  selected: ElementRef | null;
  onSelect: (ref: ElementRef) => void;
  onViewChange: (view: View) => void;
}

function Title({ children }: { children: string }) {
  return <title>{children}</title>;
}

function serviceText(inService: boolean): string {
  return inService ? "in service" : "out of service";
}

export function NetworkCanvas({ network, layout, view, selected, onSelect, onViewChange }: Props) {
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<{ x: number; y: number; view: View; moved: boolean } | null>(null);
  const suppressClick = useRef(false);

  const lines = new Map(network.lines.map((item) => [item.key, item]));
  const transformers = new Map(network.transformers.map((item) => [item.key, item]));
  const switches = new Map(network.switches.map((item) => [item.key, item]));
  const showLabels = network.buses.length <= LABEL_LIMIT;

  const select = (ref: ElementRef) => () => {
    if (suppressClick.current) return;
    onSelect(ref);
  };
  const isSelected = (ref: ElementRef) => sameRef(ref, selected);
  const elementProps = (ref: ElementRef) => ({
    "data-element": formatElementRef(ref),
    "data-selected": isSelected(ref) ? "true" : undefined,
    onClick: select(ref),
    className: "cursor-pointer",
  });

  // Drag to pan. A drag never also selects what it started on.
  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    drag.current = { x: event.clientX, y: event.clientY, view, moved: false };
    suppressClick.current = false;
  };
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const start = drag.current;
    const width = svg.current?.getBoundingClientRect().width ?? 0;
    if (start === null || width === 0) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (!start.moved && Math.hypot(dx, dy) < 4) return;
    start.moved = true;
    suppressClick.current = true;
    const unitsPerPixel = start.view.width / width;
    onViewChange(panView(start.view, dx * unitsPerPixel, dy * unitsPerPixel));
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  const glyph = (item: Glyph) => {
    const ref: ElementRef = { type: item.type, key: item.key };
    const bus = layout.buses.get(item.busKey) as Point;
    const element =
      item.type === "loads"
        ? network.loads.find((load) => load.key === item.key)
        : item.type === "generators"
          ? network.generators.find((generator) => generator.key === item.key)
          : network.externalGrids.find((grid) => grid.key === item.key);
    const inService = element?.inService ?? true;
    const tone = inService ? "stroke-ink" : MUTED;
    const dash = inService ? undefined : DASH;
    const kind =
      item.type === "loads" ? "load" : item.type === "generators" ? "generator" : "external grid";
    const { x, y } = item.at;
    return (
      <g key={formatElementRef(ref)} {...elementProps(ref)}>
        <Title>{`${element?.name ?? item.key} (${kind}), ${serviceText(inService)}`}</Title>
        <line
          x1={bus.x}
          y1={bus.y}
          x2={x}
          y2={y}
          className={tone}
          strokeWidth={1}
          strokeDasharray={dash}
        />
        {item.type === "loads" ? (
          <path
            d={`M ${x - 6} ${y - 3} L ${x + 6} ${y - 3} L ${x} ${y + 6} Z`}
            className={`${tone} fill-panel`}
            strokeWidth={1.5}
            strokeDasharray={dash}
          />
        ) : item.type === "generators" ? (
          <>
            <circle
              cx={x}
              cy={y}
              r={7}
              className={`${tone} fill-panel`}
              strokeWidth={1.5}
              strokeDasharray={dash}
            />
            <path
              d={`M ${x - 4} ${y} q 2 -4 4 0 t 4 0`}
              className={tone}
              fill="none"
              strokeWidth={1.2}
            />
          </>
        ) : (
          <>
            <rect
              x={x - 7}
              y={y - 7}
              width={14}
              height={14}
              className={`${tone} fill-panel`}
              strokeWidth={1.5}
              strokeDasharray={dash}
            />
            <path
              d={`M ${x - 7} ${y - 7} L ${x + 7} ${y + 7} M ${x + 7} ${y - 7} L ${x - 7} ${y + 7}`}
              className={tone}
              strokeWidth={1}
            />
          </>
        )}
        {isSelected(ref) ? (
          <circle cx={x} cy={y} r={11} className="stroke-accent" fill="none" strokeWidth={3} />
        ) : null}
      </g>
    );
  };

  return (
    <svg
      ref={svg}
      role="group"
      aria-label="Network diagram"
      aria-describedby="network-diagram-help"
      viewBox={viewBox(view)}
      preserveAspectRatio="xMidYMid meet"
      className="h-[32rem] w-full touch-none select-none rounded-lg border border-line bg-panel"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <desc id="network-diagram-help">
        Schematic of the stored model. Click an element to inspect it, or use the element list to
        select one with the keyboard.
      </desc>

      {layout.connections.map((shape) => {
        const ref: ElementRef = { type: shape.type, key: shape.key };
        const element =
          shape.type === "lines"
            ? lines.get(shape.key)
            : shape.type === "transformers"
              ? transformers.get(shape.key)
              : undefined;
        const coupler = shape.type === "switches" ? switches.get(shape.key) : undefined;
        const inService = element?.inService ?? true;
        const d =
          shape.control === null
            ? `M ${shape.from.x} ${shape.from.y} L ${shape.to.x} ${shape.to.y}`
            : `M ${shape.from.x} ${shape.from.y} Q ${shape.control.x} ${shape.control.y} ${shape.to.x} ${shape.to.y}`;
        const kind =
          shape.type === "lines"
            ? "line"
            : shape.type === "transformers"
              ? "transformer"
              : "bus coupler";
        const label =
          coupler !== undefined
            ? `${coupler.name} (bus coupler switch), model position ${coupler.closed ? "closed" : "open"}`
            : `${element?.name ?? shape.key} (${kind}), ${serviceText(inService)}`;
        return (
          <g key={formatElementRef(ref)} {...elementProps(ref)}>
            <Title>{label}</Title>
            <path d={d} stroke="transparent" strokeWidth={14} fill="none" />
            <path
              d={d}
              fill="none"
              className={isSelected(ref) ? "stroke-accent" : inService ? "stroke-ink" : MUTED}
              strokeWidth={isSelected(ref) ? 4 : 2}
              strokeDasharray={inService ? undefined : DASH}
            />
            {shape.type === "transformers" ? (
              <g className={inService ? "stroke-ink" : MUTED}>
                <circle
                  cx={shape.mid.x - 4}
                  cy={shape.mid.y}
                  r={7}
                  className="fill-panel"
                  strokeWidth={1.5}
                />
                <circle cx={shape.mid.x + 4} cy={shape.mid.y} r={7} fill="none" strokeWidth={1.5} />
              </g>
            ) : null}
            {coupler !== undefined ? (
              <rect
                x={shape.mid.x - 5}
                y={shape.mid.y - 5}
                width={10}
                height={10}
                data-switch-position={coupler.closed ? "closed" : "open"}
                className={`stroke-ink ${coupler.closed ? "fill-ink" : "fill-panel"}`}
                strokeWidth={1.5}
              />
            ) : null}
          </g>
        );
      })}

      {layout.switchMarkers.map((marker) => {
        const item = switches.get(marker.key);
        if (item === undefined) return null;
        const ref: ElementRef = { type: "switches", key: marker.key };
        const { x, y } = marker.at;
        return (
          <g key={formatElementRef(ref)} {...elementProps(ref)}>
            <Title>{`${item.name} (switch), model position ${item.closed ? "closed" : "open"}`}</Title>
            {/* Open: a hollow square across a gap in the line; closed: a filled square. */}
            {item.closed ? null : (
              <circle cx={x} cy={y} r={9} className="fill-panel" stroke="none" />
            )}
            <rect
              x={x - 5}
              y={y - 5}
              width={10}
              height={10}
              data-switch-position={item.closed ? "closed" : "open"}
              className={`stroke-ink ${item.closed ? "fill-ink" : "fill-panel"}`}
              strokeWidth={1.5}
            />
            {isSelected(ref) ? (
              <rect
                x={x - 9}
                y={y - 9}
                width={18}
                height={18}
                className="stroke-accent"
                fill="none"
                strokeWidth={3}
              />
            ) : null}
          </g>
        );
      })}

      {layout.glyphs.map(glyph)}

      {layout.overflows.map((overflow) => (
        <g key={`${overflow.type}:${overflow.busKey}:more`} data-overflow={overflow.type}>
          <Title>{`${overflow.count} more at this bus; see the element list`}</Title>
          <text
            x={overflow.at.x}
            y={overflow.at.y + 4}
            textAnchor="middle"
            className="fill-muted text-[10px]"
          >
            +{overflow.count}
          </text>
        </g>
      ))}

      {network.buses.map((bus) => {
        const point = layout.buses.get(bus.key);
        if (point === undefined) return null;
        const ref: ElementRef = { type: "buses", key: bus.key };
        return (
          <g key={formatElementRef(ref)} {...elementProps(ref)}>
            <Title>{`${bus.name} (bus, ${bus.nominalVoltageKv} kV), ${serviceText(bus.inService)}`}</Title>
            <rect
              x={point.x - 12}
              y={point.y - 3}
              width={24}
              height={6}
              className={
                isSelected(ref)
                  ? "fill-accent stroke-accent"
                  : bus.inService
                    ? "fill-ink stroke-ink"
                    : "fill-panel stroke-muted"
              }
              strokeWidth={bus.inService ? 1 : 1.5}
              strokeDasharray={bus.inService ? undefined : "3 2"}
            />
            {showLabels ? (
              <text
                x={point.x - 14}
                y={point.y - 7}
                textAnchor="end"
                className="fill-muted text-[10px]"
              >
                {bus.name}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}
