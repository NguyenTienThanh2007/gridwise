/**
 * A grid's whole network: `GET /api/v1/grids/{id}/topology` (decision 0009).
 *
 * Elements are identified by `key` and refer to each other by key. Only buses carry a
 * diagram position: a schematic drawing position, not geographic and not electrical. A
 * switch's `closed` is its position in the stored simulation model, not the state of any
 * real equipment.
 */

import { type ApiResult, request } from "@/lib/http/client";
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
  uuid,
} from "@/lib/resources/decode";
import { DATA_ORIGINS, type DataOrigin } from "@/lib/resources/grids";

export interface Bus {
  key: string;
  name: string;
  nominalVoltageKv: number;
  inService: boolean;
  diagram: { x: number; y: number } | null;
}

export interface Line {
  key: string;
  name: string;
  fromBusKey: string;
  toBusKey: string;
  lengthKm: number;
  rOhmPerKm: number;
  xOhmPerKm: number;
  cNfPerKm: number;
  maxIKa: number;
  inService: boolean;
}

export interface TapChanger {
  side: "hv" | "lv";
  neutralPosition: number;
  minPosition: number;
  maxPosition: number;
  stepPercent: number;
  position: number;
}

export interface Transformer {
  key: string;
  name: string;
  hvBusKey: string;
  lvBusKey: string;
  ratedPowerMva: number;
  ratedVoltageHvKv: number;
  ratedVoltageLvKv: number;
  shortCircuitVoltagePercent: number;
  shortCircuitResistivePercent: number;
  ironLossesKw: number;
  noLoadCurrentPercent: number;
  phaseShiftDegree: number;
  tap: TapChanger | null;
  inService: boolean;
}

export interface Load {
  key: string;
  name: string;
  busKey: string;
  pMw: number;
  qMvar: number;
  inService: boolean;
}

export const CONTROL_MODES = ["constant_power", "voltage_control"] as const;

export interface Generator {
  key: string;
  name: string;
  busKey: string;
  pMw: number;
  controlMode: (typeof CONTROL_MODES)[number];
  qMvar: number | null;
  voltageSetpointPu: number | null;
  minQMvar: number | null;
  maxQMvar: number | null;
  ratedPowerMva: number | null;
  inService: boolean;
}

export interface ExternalGrid {
  key: string;
  name: string;
  busKey: string;
  voltagePu: number;
  voltageAngleDegree: number;
  inService: boolean;
}

export const SWITCH_ELEMENT_TYPES = ["line", "transformer", "bus"] as const;
export const SWITCH_KINDS = [
  "circuit_breaker",
  "load_break_switch",
  "disconnector",
  "load_switch",
] as const;

export interface Switch {
  key: string;
  name: string;
  busKey: string;
  elementType: (typeof SWITCH_ELEMENT_TYPES)[number];
  elementKey: string;
  /** Position in the stored simulation model. Not a command to any equipment. */
  closed: boolean;
  kind: (typeof SWITCH_KINDS)[number];
}

export interface Network {
  frequencyHz: number;
  buses: Bus[];
  lines: Line[];
  transformers: Transformer[];
  loads: Load[];
  generators: Generator[];
  externalGrids: ExternalGrid[];
  switches: Switch[];
}

export interface Topology {
  gridId: string;
  version: number;
  topologyHash: string;
  dataOrigin: DataOrigin;
  network: Network;
}

function readBus(value: unknown): Bus {
  const o = record(value, "bus");
  const diagram = o.diagram === null || o.diagram === undefined ? null : record(o.diagram);
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    nominalVoltageKv: num(o, "nominal_voltage_kv"),
    inService: bool(o, "in_service"),
    diagram: diagram === null ? null : { x: num(diagram, "x"), y: num(diagram, "y") },
  };
}

function readLine(value: unknown): Line {
  const o = record(value, "line");
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    fromBusKey: str(o, "from_bus_key"),
    toBusKey: str(o, "to_bus_key"),
    lengthKm: num(o, "length_km"),
    rOhmPerKm: num(o, "r_ohm_per_km"),
    xOhmPerKm: num(o, "x_ohm_per_km"),
    cNfPerKm: num(o, "c_nf_per_km"),
    maxIKa: num(o, "max_i_ka"),
    inService: bool(o, "in_service"),
  };
}

function readTap(o: Record_): TapChanger {
  return {
    side: oneOf(o, "side", ["hv", "lv"] as const),
    neutralPosition: int(o, "neutral_position"),
    minPosition: int(o, "min_position"),
    maxPosition: int(o, "max_position"),
    stepPercent: num(o, "step_percent"),
    position: int(o, "position"),
  };
}

function readTransformer(value: unknown): Transformer {
  const o = record(value, "transformer");
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    hvBusKey: str(o, "hv_bus_key"),
    lvBusKey: str(o, "lv_bus_key"),
    ratedPowerMva: num(o, "rated_power_mva"),
    ratedVoltageHvKv: num(o, "rated_voltage_hv_kv"),
    ratedVoltageLvKv: num(o, "rated_voltage_lv_kv"),
    shortCircuitVoltagePercent: num(o, "short_circuit_voltage_percent"),
    shortCircuitResistivePercent: num(o, "short_circuit_resistive_percent"),
    ironLossesKw: num(o, "iron_losses_kw"),
    noLoadCurrentPercent: num(o, "no_load_current_percent"),
    phaseShiftDegree: num(o, "phase_shift_degree"),
    tap: o.tap === null || o.tap === undefined ? null : readTap(record(o.tap, "tap")),
    inService: bool(o, "in_service"),
  };
}

function readLoad(value: unknown): Load {
  const o = record(value, "load");
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    busKey: str(o, "bus_key"),
    pMw: num(o, "p_mw"),
    qMvar: num(o, "q_mvar"),
    inService: bool(o, "in_service"),
  };
}

function readGenerator(value: unknown): Generator {
  const o = record(value, "generator");
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    busKey: str(o, "bus_key"),
    pMw: num(o, "p_mw"),
    controlMode: oneOf(o, "control_mode", CONTROL_MODES),
    qMvar: nullable(o, "q_mvar", num),
    voltageSetpointPu: nullable(o, "voltage_setpoint_pu", num),
    minQMvar: nullable(o, "min_q_mvar", num),
    maxQMvar: nullable(o, "max_q_mvar", num),
    ratedPowerMva: nullable(o, "rated_power_mva", num),
    inService: bool(o, "in_service"),
  };
}

function readExternalGrid(value: unknown): ExternalGrid {
  const o = record(value, "external grid");
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    busKey: str(o, "bus_key"),
    voltagePu: num(o, "voltage_pu"),
    voltageAngleDegree: num(o, "voltage_angle_degree"),
    inService: bool(o, "in_service"),
  };
}

function readSwitch(value: unknown): Switch {
  const o = record(value, "switch");
  return {
    key: str(o, "key"),
    name: str(o, "name"),
    busKey: str(o, "bus_key"),
    elementType: oneOf(o, "element_type", SWITCH_ELEMENT_TYPES),
    elementKey: str(o, "element_key"),
    closed: bool(o, "closed"),
    kind: oneOf(o, "kind", SWITCH_KINDS),
  };
}

export function readNetwork(value: unknown): Network {
  const o = record(value, "topology");
  return {
    frequencyHz: num(o, "frequency_hz"),
    buses: list(o, "buses", readBus),
    lines: list(o, "lines", readLine),
    transformers: list(o, "transformers", readTransformer),
    loads: list(o, "loads", readLoad),
    generators: list(o, "generators", readGenerator),
    externalGrids: list(o, "external_grids", readExternalGrid),
    switches: list(o, "switches", readSwitch),
  };
}

export const decodeTopology = decoder((value): Topology => {
  const o = record(value, "topology response");
  return {
    gridId: uuid(o, "grid_id"),
    version: int(o, "version"),
    topologyHash: str(o, "topology_hash"),
    dataOrigin: oneOf(o, "data_origin", DATA_ORIGINS),
    network: readNetwork(o.topology),
  };
});

export function fetchTopology(gridId: string, signal?: AbortSignal): Promise<ApiResult<Topology>> {
  return request(`/api/v1/grids/${encodeURIComponent(gridId)}/topology`, decodeTopology, {
    signal,
  });
}
