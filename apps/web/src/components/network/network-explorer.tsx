"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { SINGULAR } from "@/components/network/describe";
import { ElementInspector } from "@/components/network/element-inspector";
import { ElementList } from "@/components/network/element-list";
import { NetworkCanvas } from "@/components/network/network-canvas";
import { NetworkLegend } from "@/components/network/network-legend";
import { DataOriginBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Notice } from "@/components/ui/notice";
import { brokenReferences, findElement } from "@/lib/network/graph";
import { type Layout, type Point, layoutNetwork } from "@/lib/network/layout";
import {
  type ElementRef,
  SELECTION_PARAMETER,
  formatElementRef,
  parseElementRef,
} from "@/lib/network/selection";
import { type View, centreOn, contains, fitView, zoomView } from "@/lib/network/view";
import type { Topology } from "@/lib/resources/topology";

/** Where an element is drawn, to bring it into view when it is chosen from the list. */
function positionOf(layout: Layout, ref: ElementRef): Point | null {
  if (ref.type === "buses") return layout.buses.get(ref.key) ?? null;
  const connection = layout.connections.find((c) => c.type === ref.type && c.key === ref.key);
  if (connection !== undefined) return connection.mid;
  if (ref.type === "switches") {
    return layout.switchMarkers.find((marker) => marker.key === ref.key)?.at ?? null;
  }
  return (
    layout.glyphs.find((glyph) => glyph.type === ref.type && glyph.key === ref.key)?.at ?? null
  );
}

function Explorer({ topology, gridId }: { topology: Topology; gridId: string }) {
  const { network } = topology;
  const broken = useMemo(() => brokenReferences(network), [network]);
  const layout = useMemo(
    () => (broken.length === 0 && network.buses.length > 0 ? layoutNetwork(network) : null),
    [broken, network],
  );
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [view, setView] = useState<View | null>(null);

  const requested = parseElementRef(searchParams.get(SELECTION_PARAMETER));
  // A selection naming an element this network does not have is ignored.
  const selected =
    requested !== null && findElement(network, requested) !== null ? requested : null;

  if (broken.length > 0) {
    return (
      <Notice tone="bad" title="This topology cannot be drawn" role="alert">
        <p>
          It refers to elements that do not exist, so drawing it would mean guessing connections.
          Nothing is drawn.
        </p>
        <ul className="mt-2 list-disc pl-5">
          {broken.map((item) => (
            <li key={`${formatElementRef(item.element)}:${item.field}`}>
              {SINGULAR[item.element.type]} <code>{item.element.key}</code>: {item.field} refers to{" "}
              <code>{item.target}</code>
            </li>
          ))}
        </ul>
      </Notice>
    );
  }
  if (layout === null) {
    return <EmptyState title="This grid has no buses to draw" />;
  }

  const current = view ?? fitView(layout.bounds);
  const select = (ref: ElementRef, bringIntoView: boolean) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set(SELECTION_PARAMETER, formatElementRef(ref));
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    const point = bringIntoView ? positionOf(layout, ref) : null;
    if (point !== null && !contains(current, point)) setView(centreOn(current, point));
  };

  return (
    <>
      {layout.source === "fallback" ? (
        <div className="mb-4">
          <Notice title="Schematic layout">
            {layout.missingPositions} of {network.buses.length} buses have no stored diagram
            position, so every bus is placed automatically from the network&apos;s connections.
          </Notice>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <DataOriginBadge origin={topology.dataOrigin} />
              <p className="text-xs text-muted">
                Schematic of the stored model: drawing positions, not geography. No live
                measurements or electrical state.
              </p>
            </div>
            <div role="group" aria-label="Diagram view" className="flex gap-1">
              <Button onClick={() => setView(zoomView(current, 0.8, layout.bounds))}>
                Zoom in
              </Button>
              <Button onClick={() => setView(zoomView(current, 1.25, layout.bounds))}>
                Zoom out
              </Button>
              <Button onClick={() => setView(null)}>Fit</Button>
            </div>
          </div>
          <div className="hidden md:block">
            <NetworkCanvas
              network={network}
              layout={layout}
              view={current}
              selected={selected}
              onSelect={(ref) => select(ref, false)}
              onViewChange={setView}
            />
            <NetworkLegend />
          </div>
        </div>
        <div className="space-y-4">
          <ElementInspector
            network={network}
            selected={selected}
            onSelect={(ref) => select(ref, true)}
            editHref={(ref) =>
              `/grid/${gridId}/assets?${SELECTION_PARAMETER}=${encodeURIComponent(formatElementRef(ref))}`
            }
          />
          <ElementList
            network={network}
            selected={selected}
            onSelect={(ref) => select(ref, true)}
          />
        </div>
      </div>
    </>
  );
}

/** The stored network of one grid; the grid workspace loads it with the grid's details. */
export function NetworkExplorer({ topology, gridId }: { topology: Topology; gridId: string }) {
  return (
    <section aria-labelledby="network-title" className="mt-8">
      <h2 id="network-title" className="mb-3 text-lg font-semibold">
        Network
      </h2>
      <Explorer topology={topology} gridId={gridId} />
    </section>
  );
}
