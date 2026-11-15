/**
 * TEST FIXTURES ONLY. Small decoded networks for layout and explorer tests. Invented for
 * tests, not data: never imported by application code (a test checks that).
 */

import type {
  Bus,
  ExternalGrid,
  Generator,
  Line,
  Load,
  Network,
  Switch,
  Transformer,
} from "@/lib/resources/topology";

export function bus(
  key: string,
  diagram: { x: number; y: number } | null = null,
  extra: Partial<Bus> = {},
): Bus {
  return { key, name: `Bus ${key}`, nominalVoltageKv: 20, inService: true, diagram, ...extra };
}

export function line(
  key: string,
  fromBusKey: string,
  toBusKey: string,
  extra: Partial<Line> = {},
): Line {
  return {
    key,
    name: `Line ${key}`,
    fromBusKey,
    toBusKey,
    lengthKm: 1,
    rOhmPerKm: 0.5,
    xOhmPerKm: 0.4,
    cNfPerKm: 10,
    maxIKa: 0.3,
    inService: true,
    ...extra,
  };
}

export function transformer(key: string, hvBusKey: string, lvBusKey: string): Transformer {
  return {
    key,
    name: `Transformer ${key}`,
    hvBusKey,
    lvBusKey,
    ratedPowerMva: 25,
    ratedVoltageHvKv: 110,
    ratedVoltageLvKv: 20,
    shortCircuitVoltagePercent: 12,
    shortCircuitResistivePercent: 0.4,
    ironLossesKw: 14,
    noLoadCurrentPercent: 0.07,
    phaseShiftDegree: 0,
    tap: null,
    inService: true,
  };
}

export function load(key: string, busKey: string, extra: Partial<Load> = {}): Load {
  return { key, name: `Load ${key}`, busKey, pMw: 1, qMvar: 0.2, inService: true, ...extra };
}

export function generator(key: string, busKey: string): Generator {
  return {
    key,
    name: `Generator ${key}`,
    busKey,
    pMw: 0.5,
    controlMode: "constant_power",
    qMvar: 0,
    voltageSetpointPu: null,
    minQMvar: null,
    maxQMvar: null,
    ratedPowerMva: null,
    inService: true,
  };
}

export function externalGrid(key: string, busKey: string): ExternalGrid {
  return {
    key,
    name: `External ${key}`,
    busKey,
    voltagePu: 1,
    voltageAngleDegree: 0,
    inService: true,
  };
}

export function switchAt(
  key: string,
  busKey: string,
  elementType: Switch["elementType"],
  elementKey: string,
  closed: boolean,
): Switch {
  return {
    key,
    name: `Switch ${key}`,
    busKey,
    elementType,
    elementKey,
    closed,
    kind: "load_break_switch",
  };
}

export function network(parts: Partial<Network>): Network {
  return {
    frequencyHz: 50,
    buses: [],
    lines: [],
    transformers: [],
    loads: [],
    generators: [],
    externalGrids: [],
    switches: [],
    ...parts,
  };
}

/** A small feeder with stored positions: hv → (t1) → a → b → c, ring line c–a. */
export function feeder(): Network {
  return network({
    buses: [
      bus("hv", { x: 0, y: 4 }, { nominalVoltageKv: 110 }),
      bus("a", { x: 0, y: 2 }),
      bus("b", { x: 2, y: 2 }),
      bus("c", { x: 2, y: 0 }, { inService: false }),
    ],
    transformers: [transformer("t1", "hv", "a")],
    lines: [
      line("l-ab", "a", "b"),
      line("l-bc", "b", "c"),
      line("l-ca", "c", "a", { inService: false }),
    ],
    loads: [load("load-b", "b"), load("load-c", "c")],
    generators: [generator("pv-b", "b")],
    externalGrids: [externalGrid("upstream", "hv")],
    switches: [
      switchAt("s-bc", "c", "line", "l-bc", false),
      switchAt("s-ab", "a", "line", "l-ab", true),
    ],
  });
}
