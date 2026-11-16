"use client";

import { useId, useState } from "react";
import { stateText } from "@/components/network/describe";
import { elementsOf, naturalCompare } from "@/lib/network/graph";
import { type ElementRef, sameRef } from "@/lib/network/selection";
import { ELEMENT_TYPES, ELEMENT_TYPE_LABELS } from "@/lib/resources/grids";
import type { Network } from "@/lib/resources/topology";

/** The keyboard path to every element: a filter and one button per element, by type. */
export function ElementList({
  network,
  selected,
  onSelect,
}: {
  network: Network;
  selected: ElementRef | null;
  onSelect: (ref: ElementRef) => void;
}) {
  const [filter, setFilter] = useState("");
  const filterId = useId();
  const needle = filter.trim().toLowerCase();

  const groups = ELEMENT_TYPES.map((type) => ({
    type,
    items: [...elementsOf(network, type)]
      .sort((a, b) => naturalCompare(a.key, b.key))
      .filter(
        (element) =>
          needle === "" ||
          element.key.toLowerCase().includes(needle) ||
          element.name.toLowerCase().includes(needle),
      ),
  })).filter((group) => group.items.length > 0);

  return (
    <section
      aria-labelledby="element-list-title"
      className="rounded-panel border border-line bg-panel"
    >
      <div className="border-b border-line p-3">
        <h3 id="element-list-title" className="text-sm font-medium">
          Elements
        </h3>
        <label htmlFor={filterId} className="mt-2 block text-xs text-muted">
          Filter by name or key
        </label>
        <input
          id={filterId}
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          className="mt-1 w-full rounded-control border border-line px-2 py-1 text-sm"
        />
      </div>
      <div className="max-h-[28rem] overflow-y-auto p-2">
        {groups.length === 0 ? (
          <p className="p-2 text-sm text-muted">No element matches “{filter}”.</p>
        ) : (
          groups.map((group) => (
            <div key={group.type} className="mb-2">
              <h4 className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-muted">
                {ELEMENT_TYPE_LABELS[group.type]} ({group.items.length})
              </h4>
              <ul>
                {group.items.map((element) => {
                  const ref: ElementRef = { type: group.type, key: element.key };
                  const active = sameRef(ref, selected);
                  const state = stateText(element);
                  return (
                    <li key={element.key}>
                      <button
                        type="button"
                        aria-pressed={active}
                        onClick={() => onSelect(ref)}
                        className={`flex w-full items-baseline justify-between gap-2 rounded-control px-2 py-1 text-left text-sm ${
                          active ? "bg-accent/10 font-medium text-accent" : "hover:bg-surface"
                        }`}
                      >
                        <span>
                          {element.name} <span className="text-xs text-muted">{element.key}</span>
                        </span>
                        {state === null ? null : (
                          <span className="text-xs text-muted">{state}</span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
