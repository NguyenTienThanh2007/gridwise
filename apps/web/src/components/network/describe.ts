/** Names and state text for elements, shared by the list and the inspector. */

import type { NetworkElement } from "@/lib/network/graph";
import type { ElementType } from "@/lib/resources/grids";

export const SINGULAR: Record<ElementType, string> = {
  buses: "Bus",
  lines: "Line",
  transformers: "Transformer",
  loads: "Load",
  generators: "Generator",
  external_grids: "External grid",
  switches: "Switch",
};

/** "Out of service", "Model position: open", or null when there is nothing to note. */
export function stateText(element: NetworkElement): string | null {
  if ("closed" in element) return `Model position: ${element.closed ? "closed" : "open"}`;
  return element.inService ? null : "Out of service";
}
