"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { SINGULAR, stateText } from "@/components/network/describe";
import { Value } from "@/components/ui/value";
import { elementsAtBus, findElement } from "@/lib/network/graph";
import type { ElementRef } from "@/lib/network/selection";
import type { Network } from "@/lib/resources/topology";
import { Property, PropertyList } from "@/components/ui/property-list";

const SWITCH_KIND_LABELS = {
  circuit_breaker: "Circuit breaker",
  load_break_switch: "Load-break switch",
  disconnector: "Disconnector",
  load_switch: "Load switch",
} as const;

const CONTROL_MODE_LABELS = {
  constant_power: "Constant power (P, Q)",
  voltage_control: "Voltage control (P, V)",
} as const;

function Quantity({ value, unit }: { value: number; unit: string }) {
  return <Value value={value} unit={unit} reason="not set" />;
}

/** Everything the stored model holds about the selected element, and its references. */
export function ElementInspector({
  network,
  selected,
  onSelect,
  editHref,
  children,
}: {
  network: Network;
  selected: ElementRef | null;
  onSelect: (ref: ElementRef) => void;
  /** Where this element can be edited; the inspector itself never changes anything. */
  editHref?: (ref: ElementRef) => string;
  /** Shown under the stored values, for example an edit form. */
  children?: ReactNode;
}) {
  const element = selected === null ? null : findElement(network, selected);

  const reference = (ref: ElementRef) => {
    const target = findElement(network, ref);
    return (
      <button
        type="button"
        onClick={() => onSelect(ref)}
        className="text-left text-accent underline-offset-2 hover:underline"
      >
        {target?.name ?? ref.key} <span className="text-xs text-muted">{ref.key}</span>
      </button>
    );
  };
  const service = (inService: boolean) => (inService ? "In service" : "Out of service");

  let rows: ReactNode = null;
  if (selected !== null && element !== null) {
    switch (selected.type) {
      case "buses": {
        const bus = network.buses.find((item) => item.key === selected.key);
        if (bus === undefined) break;
        rows = (
          <>
            <Property label="Nominal voltage">
              <Quantity value={bus.nominalVoltageKv} unit="kV" />
            </Property>
            <Property label="Service state">{service(bus.inService)}</Property>
            <Property label="Diagram position">
              {bus.diagram === null ? (
                <span className="text-muted">None stored</span>
              ) : (
                <span className="tabular-nums">{`${bus.diagram.x}, ${bus.diagram.y}`}</span>
              )}
            </Property>
          </>
        );
        break;
      }
      case "lines": {
        const line = network.lines.find((item) => item.key === selected.key);
        if (line === undefined) break;
        rows = (
          <>
            <Property label="From bus">
              {reference({ type: "buses", key: line.fromBusKey })}
            </Property>
            <Property label="To bus">{reference({ type: "buses", key: line.toBusKey })}</Property>
            <Property label="Length">
              <Quantity value={line.lengthKm} unit="km" />
            </Property>
            <Property label="Resistance">
              <Quantity value={line.rOhmPerKm} unit="Ω/km" />
            </Property>
            <Property label="Reactance">
              <Quantity value={line.xOhmPerKm} unit="Ω/km" />
            </Property>
            <Property label="Capacitance">
              <Quantity value={line.cNfPerKm} unit="nF/km" />
            </Property>
            <Property label="Thermal limit">
              <Quantity value={line.maxIKa} unit="kA" />
            </Property>
            <Property label="Service state">{service(line.inService)}</Property>
          </>
        );
        break;
      }
      case "transformers": {
        const item = network.transformers.find((candidate) => candidate.key === selected.key);
        if (item === undefined) break;
        rows = (
          <>
            <Property label="HV bus">{reference({ type: "buses", key: item.hvBusKey })}</Property>
            <Property label="LV bus">{reference({ type: "buses", key: item.lvBusKey })}</Property>
            <Property label="Rated power">
              <Quantity value={item.ratedPowerMva} unit="MVA" />
            </Property>
            <Property label="Rated voltage HV">
              <Quantity value={item.ratedVoltageHvKv} unit="kV" />
            </Property>
            <Property label="Rated voltage LV">
              <Quantity value={item.ratedVoltageLvKv} unit="kV" />
            </Property>
            <Property label="Short-circuit voltage">
              <Quantity value={item.shortCircuitVoltagePercent} unit="%" />
            </Property>
            <Property label="Resistive part">
              <Quantity value={item.shortCircuitResistivePercent} unit="%" />
            </Property>
            <Property label="Iron losses">
              <Quantity value={item.ironLossesKw} unit="kW" />
            </Property>
            <Property label="No-load current">
              <Quantity value={item.noLoadCurrentPercent} unit="%" />
            </Property>
            <Property label="Phase shift">
              <Quantity value={item.phaseShiftDegree} unit="°" />
            </Property>
            <Property label="Tap changer">
              {item.tap === null ? (
                <span className="text-muted">None</span>
              ) : (
                <span className="tabular-nums">
                  {`${item.tap.side.toUpperCase()} side, position ${item.tap.position} (${item.tap.minPosition} to ${item.tap.maxPosition}, neutral ${item.tap.neutralPosition}), ${item.tap.stepPercent} % per step`}
                </span>
              )}
            </Property>
            <Property label="Service state">{service(item.inService)}</Property>
          </>
        );
        break;
      }
      case "loads": {
        const item = network.loads.find((candidate) => candidate.key === selected.key);
        if (item === undefined) break;
        rows = (
          <>
            <Property label="Bus">{reference({ type: "buses", key: item.busKey })}</Property>
            <Property label="Active power">
              <Quantity value={item.pMw} unit="MW" />
            </Property>
            <Property label="Reactive power">
              <Quantity value={item.qMvar} unit="Mvar" />
            </Property>
            <Property label="Service state">{service(item.inService)}</Property>
          </>
        );
        break;
      }
      case "generators": {
        const item = network.generators.find((candidate) => candidate.key === selected.key);
        if (item === undefined) break;
        rows = (
          <>
            <Property label="Bus">{reference({ type: "buses", key: item.busKey })}</Property>
            <Property label="Control mode">{CONTROL_MODE_LABELS[item.controlMode]}</Property>
            <Property label="Active power">
              <Quantity value={item.pMw} unit="MW" />
            </Property>
            <Property label="Reactive power">
              <Value value={item.qMvar} unit="Mvar" reason="not set" />
            </Property>
            <Property label="Voltage set-point">
              <Value value={item.voltageSetpointPu} unit="p.u." reason="not set" />
            </Property>
            <Property label="Minimum reactive power">
              <Value value={item.minQMvar} unit="Mvar" reason="not set" />
            </Property>
            <Property label="Maximum reactive power">
              <Value value={item.maxQMvar} unit="Mvar" reason="not set" />
            </Property>
            <Property label="Rated power">
              <Value value={item.ratedPowerMva} unit="MVA" reason="not set" />
            </Property>
            <Property label="Service state">{service(item.inService)}</Property>
          </>
        );
        break;
      }
      case "external_grids": {
        const item = network.externalGrids.find((candidate) => candidate.key === selected.key);
        if (item === undefined) break;
        rows = (
          <>
            <Property label="Bus">{reference({ type: "buses", key: item.busKey })}</Property>
            <Property label="Voltage set-point">
              <Quantity value={item.voltagePu} unit="p.u." />
            </Property>
            <Property label="Voltage angle">
              <Quantity value={item.voltageAngleDegree} unit="°" />
            </Property>
            <Property label="Service state">{service(item.inService)}</Property>
          </>
        );
        break;
      }
      case "switches": {
        const item = network.switches.find((candidate) => candidate.key === selected.key);
        if (item === undefined) break;
        const target: ElementRef =
          item.elementType === "line"
            ? { type: "lines", key: item.elementKey }
            : item.elementType === "transformer"
              ? { type: "transformers", key: item.elementKey }
              : { type: "buses", key: item.elementKey };
        rows = (
          <>
            <Property label="Model position">{item.closed ? "Closed" : "Open"}</Property>
            <Property label="Kind">{SWITCH_KIND_LABELS[item.kind]}</Property>
            <Property label="At bus">{reference({ type: "buses", key: item.busKey })}</Property>
            <Property
              label={item.elementType === "bus" ? "Couples to bus" : `On ${item.elementType}`}
            >
              {reference(target)}
            </Property>
          </>
        );
        break;
      }
    }
  }

  const connected =
    selected?.type === "buses" && element !== null ? elementsAtBus(network, selected.key) : [];
  const state = element === null ? null : stateText(element);

  return (
    <section
      aria-labelledby="inspector-title"
      className="rounded-panel border border-line bg-panel p-4"
    >
      <div aria-live="polite">
        <h3 id="inspector-title" className="text-sm font-medium text-muted">
          {selected === null || element === null ? "Inspector" : SINGULAR[selected.type]}
        </h3>
        {selected === null || element === null ? (
          <p className="mt-2 text-sm text-muted">
            Select an element in the diagram or in the element list.
          </p>
        ) : (
          <p className="mt-1 text-lg font-semibold">
            {element.name} <span className="text-sm font-normal text-muted">{element.key}</span>
          </p>
        )}
        {state === null ? null : <p className="mt-1 text-sm font-medium">{state}</p>}
      </div>
      {rows === null ? null : (
        <PropertyList className="mt-3 border-t border-line">{rows}</PropertyList>
      )}
      {connected.length === 0 ? null : (
        <div className="mt-4">
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted">
            Connected at this bus ({connected.length})
          </h4>
          <ul className="mt-1 space-y-1 text-sm">
            {connected.map((ref) => (
              <li key={`${ref.type}:${ref.key}`}>
                <span className="text-xs text-muted">{SINGULAR[ref.type]}: </span>
                {reference(ref)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {element === null ? null : (
        <p className="mt-4 text-xs text-muted">Stored model values. Not measurements.</p>
      )}
      {selected === null || element === null || editHref === undefined ? null : (
        <p className="mt-3 text-sm">
          <Link href={editHref(selected)} className="text-accent hover:underline">
            Edit in Assets
          </Link>
        </p>
      )}
      {element === null ? null : children}
    </section>
  );
}
