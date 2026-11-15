/**
 * Scenarios: `/api/v1/scenarios` (decision 0013). A scenario is an immutable, named list of
 * changes applied to a copy of a grid before it is simulated. It never changes a stored grid,
 * and `set_switch` changes the simulated copy's model position only: nothing reaches any
 * equipment. Scenarios are created and deleted, never edited.
 */

import { type ApiResult, noContent, request } from "@/lib/http/client";
import {
  type Record_,
  bool,
  decoder,
  int,
  list,
  nullable,
  num,
  oneOf,
  record,
  str,
  timestamp,
  uuid,
} from "@/lib/resources/decode";

export const SCENARIO_ELEMENT_TYPES = [
  "bus",
  "line",
  "transformer",
  "load",
  "generator",
  "external_grid",
] as const;
export type ScenarioElementType = (typeof SCENARIO_ELEMENT_TYPES)[number];

export const GENERATION_CONTROL_MODES = ["constant_power", "voltage_control"] as const;

export type Modification =
  | { type: "scale_loads"; factor: number; keys: string[] | null }
  | {
      type: "scale_generation";
      factor: number;
      keys: string[] | null;
      controlMode: (typeof GENERATION_CONTROL_MODES)[number] | null;
    }
  | { type: "set_in_service"; elementType: ScenarioElementType; key: string; inService: boolean }
  | { type: "set_switch"; key: string; closed: boolean };

export interface Specification {
  schema: string;
  modifications: Modification[];
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  specHash: string;
  specification: Specification;
  createdAt: string;
}

export interface ScenarioPage {
  items: Scenario[];
  total: number;
  limit: number;
  offset: number;
}

const MODIFICATION_TYPES = [
  "scale_loads",
  "scale_generation",
  "set_in_service",
  "set_switch",
] as const;

function keys(o: Record_): string[] | null {
  return o.keys === null || o.keys === undefined
    ? null
    : list(o, "keys", (value) => {
        if (typeof value !== "string") throw new TypeError("key");
        return value;
      });
}

export function readModification(value: unknown): Modification {
  const o = record(value, "modification");
  const type = oneOf(o, "type", MODIFICATION_TYPES);
  switch (type) {
    case "scale_loads":
      return { type, factor: num(o, "factor"), keys: keys(o) };
    case "scale_generation":
      return {
        type,
        factor: num(o, "factor"),
        keys: keys(o),
        controlMode: nullable(o, "control_mode", (obj, name) =>
          oneOf(obj, name, GENERATION_CONTROL_MODES),
        ),
      };
    case "set_in_service":
      return {
        type,
        elementType: oneOf(o, "element_type", SCENARIO_ELEMENT_TYPES),
        key: str(o, "key"),
        inService: bool(o, "in_service"),
      };
    case "set_switch":
      return { type, key: str(o, "key"), closed: bool(o, "closed") };
  }
}

export function readSpecification(value: unknown): Specification {
  const o = record(value, "specification");
  return { schema: str(o, "schema"), modifications: list(o, "modifications", readModification) };
}

function readScenario(value: unknown): Scenario {
  const o = record(value, "scenario");
  return {
    id: uuid(o, "id"),
    name: str(o, "name"),
    description: str(o, "description"),
    specHash: str(o, "spec_hash"),
    specification: readSpecification(o.specification),
    createdAt: timestamp(o, "created_at"),
  };
}

export const decodeScenario = decoder(readScenario);
export const decodeScenarioPage = decoder((value): ScenarioPage => {
  const o = record(value, "scenario list");
  return {
    items: list(o, "items", readScenario),
    total: int(o, "total"),
    limit: int(o, "limit"),
    offset: int(o, "offset"),
  };
});

/** The request body, in the API's field names. */
export function modificationBody(modification: Modification): Record<string, unknown> {
  switch (modification.type) {
    case "scale_loads":
      return {
        type: modification.type,
        factor: modification.factor,
        ...(modification.keys === null ? {} : { keys: modification.keys }),
      };
    case "scale_generation":
      return {
        type: modification.type,
        factor: modification.factor,
        ...(modification.keys === null ? {} : { keys: modification.keys }),
        ...(modification.controlMode === null ? {} : { control_mode: modification.controlMode }),
      };
    case "set_in_service":
      return {
        type: modification.type,
        element_type: modification.elementType,
        key: modification.key,
        in_service: modification.inService,
      };
    case "set_switch":
      return { type: modification.type, key: modification.key, closed: modification.closed };
  }
}

export function fetchScenarios(
  { limit, offset }: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<ApiResult<ScenarioPage>> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return request(`/api/v1/scenarios?${query}`, decodeScenarioPage, { signal });
}

export function createScenario(input: {
  name: string;
  description: string;
  modifications: Modification[];
}): Promise<ApiResult<Scenario>> {
  return request("/api/v1/scenarios", decodeScenario, {
    method: "POST",
    body: {
      name: input.name,
      description: input.description,
      modifications: input.modifications.map(modificationBody),
    },
  });
}

export function deleteScenario(id: string): Promise<ApiResult<true>> {
  return request(`/api/v1/scenarios/${encodeURIComponent(id)}`, noContent, { method: "DELETE" });
}

/** One line per change, in plain words: what the scenario does to the simulated copy. */
export function describeModification(modification: Modification): string {
  const scope = (k: string[] | null, all: string) => (k === null ? all : k.join(", "));
  switch (modification.type) {
    case "scale_loads":
      return `Scale loads (${scope(modification.keys, "all")}) by ${modification.factor}`;
    case "scale_generation":
      return `Scale generation (${scope(modification.keys, "all")}${
        modification.controlMode === null
          ? ""
          : `, ${modification.controlMode.replace("_", " ")} only`
      }) by ${modification.factor}`;
    case "set_in_service":
      return `${modification.inService ? "Put" : "Take"} ${modification.elementType.replace("_", " ")} ${modification.key} ${modification.inService ? "in" : "out of"} service`;
    case "set_switch":
      return `Set switch ${modification.key} to ${modification.closed ? "closed" : "open"} (model position)`;
  }
}
