/** Which element is selected, as a typed reference and as the `element` query parameter. */

import { ELEMENT_TYPES, type ElementType } from "@/lib/resources/grids";

export interface ElementRef {
  type: ElementType;
  key: string;
}

export const SELECTION_PARAMETER = "element";

/** `lines:line-6-7` → `{type: "lines", key: "line-6-7"}`; anything else → null. */
export function parseElementRef(value: string | null | undefined): ElementRef | null {
  if (value === null || value === undefined) return null;
  const separator = value.indexOf(":");
  if (separator <= 0) return null;
  const type = ELEMENT_TYPES.find((candidate) => candidate === value.slice(0, separator));
  const key = value.slice(separator + 1);
  if (type === undefined || key === "") return null;
  return { type, key };
}

export function formatElementRef(ref: ElementRef): string {
  return `${ref.type}:${ref.key}`;
}

export function sameRef(a: ElementRef | null, b: ElementRef | null): boolean {
  return a !== null && b !== null && a.type === b.type && a.key === b.key;
}
