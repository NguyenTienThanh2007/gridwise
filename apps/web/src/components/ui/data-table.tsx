import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  /** Right-aligned with tabular figures, for numbers. */
  numeric?: boolean;
  /** Keep the cell on one line (timestamps, ids, chips). */
  nowrap?: boolean;
}

/**
 * The one table of GRIDWISE: aligned columns, a sticky header, and, on narrow screens, its
 * own horizontal scroll, never the page's.
 */
export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  isSelected,
  rowAttributes,
}: {
  caption: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Highlights the row (the control that selects it carries aria-pressed). */
  isSelected?: (row: T) => boolean;
  /** Extra attributes on each row, for example data-* hooks for tests. */
  rowAttributes?: (row: T) => Record<string, string>;
}) {
  return (
    <div className="overflow-x-auto rounded-panel border border-line bg-panel">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line bg-sunken text-left">
            {columns.map((column) => (
              <th
                key={column.header}
                scope="col"
                className={`sticky top-0 h-8 whitespace-nowrap bg-sunken px-3 text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-muted ${column.numeric ? "text-right" : ""}`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selected = isSelected?.(row) ?? false;
            return (
              <tr
                key={rowKey(row)}
                {...rowAttributes?.(row)}
                className={`border-b border-line last:border-b-0 ${selected ? "bg-accent-subtle" : "hover:bg-sunken/50"}`}
              >
                {columns.map((column) => (
                  <td
                    key={column.header}
                    className={`h-9 px-3 py-1.5 align-middle ${column.numeric ? "text-right tabular-nums" : ""} ${column.nowrap ? "whitespace-nowrap" : ""}`}
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
