import type { ReactNode } from "react";
import { SINGULAR, stateText } from "@/components/network/describe";
import { formatQuantity } from "@/lib/format";
import type { AssetRow } from "@/lib/assets/filter";
import { type ElementRef, sameRef } from "@/lib/network/selection";
import type { ElementType } from "@/lib/resources/grids";
import type { Network } from "@/lib/resources/topology";

interface Column {
  header: string;
  cell: (row: AssetRow) => ReactNode;
  numeric?: boolean;
}

function busName(network: Network, key: string): string {
  return network.buses.find((bus) => bus.key === key)?.name ?? key;
}

function connects(network: Network, row: AssetRow): string {
  const e = row.element;
  if ("fromBusKey" in e)
    return `${busName(network, e.fromBusKey)} – ${busName(network, e.toBusKey)}`;
  if ("hvBusKey" in e) return `${busName(network, e.hvBusKey)} – ${busName(network, e.lvBusKey)}`;
  if ("busKey" in e) return busName(network, e.busKey);
  return "";
}

/** Type-specific columns, from the stored fields only. */
function specific(type: ElementType): Column[] {
  const q = (value: number, unit: string) => formatQuantity(value, unit);
  switch (type) {
    case "buses":
      return [
        {
          header: "Nominal voltage",
          cell: (r) =>
            "nominalVoltageKv" in r.element ? q(r.element.nominalVoltageKv, "kV") : null,
          numeric: true,
        },
      ];
    case "lines":
      return [
        {
          header: "Length",
          cell: (r) => ("lengthKm" in r.element ? q(r.element.lengthKm, "km") : null),
          numeric: true,
        },
        {
          header: "Thermal limit",
          cell: (r) => ("maxIKa" in r.element ? q(r.element.maxIKa, "kA") : null),
          numeric: true,
        },
      ];
    case "transformers":
      return [
        {
          header: "Rated power",
          cell: (r) => ("hvBusKey" in r.element ? q(r.element.ratedPowerMva, "MVA") : null),
          numeric: true,
        },
      ];
    case "loads":
      return [
        {
          header: "P",
          cell: (r) => ("pMw" in r.element ? q(r.element.pMw, "MW") : null),
          numeric: true,
        },
        {
          header: "Q",
          cell: (r) =>
            "qMvar" in r.element && r.element.qMvar !== null ? q(r.element.qMvar, "Mvar") : null,
          numeric: true,
        },
      ];
    case "generators":
      return [
        {
          header: "P",
          cell: (r) => ("pMw" in r.element ? q(r.element.pMw, "MW") : null),
          numeric: true,
        },
      ];
    case "external_grids":
      return [
        {
          header: "Voltage set-point",
          cell: (r) => ("voltagePu" in r.element ? q(r.element.voltagePu, "p.u.") : null),
          numeric: true,
        },
      ];
    case "switches":
      return [
        {
          header: "On",
          cell: (r) =>
            "elementKey" in r.element ? `${r.element.elementType} ${r.element.elementKey}` : null,
        },
      ];
  }
}

export function AssetTable({
  network,
  rows,
  type,
  selected,
  onSelect,
}: {
  network: Network;
  rows: AssetRow[];
  type: ElementType | "all";
  selected: ElementRef | null;
  onSelect: (ref: ElementRef) => void;
}) {
  const columns: Column[] = [
    ...(type === "all" ? [{ header: "Type", cell: (r: AssetRow) => SINGULAR[r.type] }] : []),
    {
      header: "Name",
      cell: (r) => {
        const ref = { type: r.type, key: r.element.key };
        return (
          <button
            type="button"
            aria-pressed={sameRef(ref, selected)}
            onClick={() => onSelect(ref)}
            className="text-left font-medium text-accent hover:underline"
          >
            {r.element.name}
          </button>
        );
      },
    },
    { header: "Key", cell: (r) => <code className="text-xs">{r.element.key}</code> },
    { header: "Connects to", cell: (r) => connects(network, r) },
    ...(type === "all" ? [] : specific(type)),
    { header: "State", cell: (r) => stateText(r.element) ?? "In service" },
  ];

  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-panel">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Assets of this grid</caption>
        <thead>
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
            {columns.map((column) => (
              <th
                key={column.header}
                scope="col"
                className={`px-3 py-2 font-medium ${column.numeric ? "text-right" : ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = sameRef({ type: row.type, key: row.element.key }, selected);
            return (
              <tr
                key={`${row.type}:${row.element.key}`}
                data-asset={`${row.type}:${row.element.key}`}
                className={`border-b border-line last:border-b-0 ${active ? "bg-accent/10" : ""}`}
              >
                {columns.map((column) => (
                  <td
                    key={column.header}
                    className={`px-3 py-2 ${column.numeric ? "text-right tabular-nums" : ""}`}
                  >
                    {column.cell(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
