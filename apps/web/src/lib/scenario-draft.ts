/**
 * A scenario being written in the form: text as typed, checked against the same rules as
 * the API and the engine (gridwise.scenario/1), and turned into modifications to send.
 */

import type { GENERATION_CONTROL_MODES } from "@/lib/resources/scenarios";
import {
  type Modification,
  SCENARIO_ELEMENT_TYPES,
  type ScenarioElementType,
} from "@/lib/resources/scenarios";

export const MAX_MODIFICATIONS = 200;
export const MAX_SCALE_FACTOR = 100;
const KEY = /^[A-Za-z0-9._-]{1,200}$/;

export interface DraftChange {
  id: number;
  type: Modification["type"];
  factor: string;
  /** Comma- or space-separated element keys; empty means every element of the kind. */
  keys: string;
  controlMode: "" | (typeof GENERATION_CONTROL_MODES)[number];
  elementType: ScenarioElementType;
  key: string;
  /** in_service for set_in_service, closed for set_switch. */
  flag: boolean;
}

export function blankChange(id: number): DraftChange {
  return {
    id,
    type: "scale_loads",
    factor: "1.2",
    keys: "",
    controlMode: "",
    elementType: "line",
    key: "",
    flag: false,
  };
}

export type ChangeErrors = Partial<Record<"factor" | "keys" | "key", string>>;

function parseKeys(text: string): string[] {
  return text.split(/[\s,]+/).filter((part) => part !== "");
}

export function changeErrors(change: DraftChange): ChangeErrors {
  const errors: ChangeErrors = {};
  if (change.type === "scale_loads" || change.type === "scale_generation") {
    const factor = Number(change.factor);
    const lower = change.type === "scale_loads" ? "above 0" : "0 or more";
    const low = change.type === "scale_loads" ? factor <= 0 : factor < 0;
    if (
      change.factor.trim() === "" ||
      !Number.isFinite(factor) ||
      low ||
      factor > MAX_SCALE_FACTOR
    ) {
      errors.factor = `Use a number ${lower} and at most ${MAX_SCALE_FACTOR}.`;
    }
    const bad = parseKeys(change.keys).find((key) => !KEY.test(key));
    if (bad !== undefined) errors.keys = `"${bad}" is not an element key (letters, digits, . _ -).`;
  } else if (!KEY.test(change.key)) {
    errors.key = "Enter the element's key (letters, digits, . _ -).";
  }
  return errors;
}

export function toModification(change: DraftChange): Modification {
  const keys = parseKeys(change.keys);
  switch (change.type) {
    case "scale_loads":
      return {
        type: change.type,
        factor: Number(change.factor),
        keys: keys.length === 0 ? null : keys,
      };
    case "scale_generation":
      return {
        type: change.type,
        factor: Number(change.factor),
        keys: keys.length === 0 ? null : keys,
        controlMode: change.controlMode === "" ? null : change.controlMode,
      };
    case "set_in_service":
      return {
        type: change.type,
        elementType: change.elementType,
        key: change.key,
        inService: change.flag,
      };
    case "set_switch":
      return { type: change.type, key: change.key, closed: change.flag };
  }
}

export const CHANGE_TYPE_LABELS: Record<Modification["type"], string> = {
  scale_loads: "Scale loads",
  scale_generation: "Scale generation",
  set_in_service: "Set service state",
  set_switch: "Set switch model position",
};

export const ELEMENT_TYPE_LABELS: Record<ScenarioElementType, string> = {
  bus: "Bus",
  line: "Line",
  transformer: "Transformer",
  load: "Load",
  generator: "Generator",
  external_grid: "External grid",
};

export { SCENARIO_ELEMENT_TYPES };
