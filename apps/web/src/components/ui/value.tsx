import { formatQuantity } from "@/lib/format";

/**
 * A number from the API, or "–" when the API has none. A missing value is never shown as
 * zero; `reason` says why it is missing ("not set", "de-energised").
 */
export function Value({
  value,
  unit = "",
  reason,
}: {
  value: number | null;
  unit?: string;
  reason: string;
}) {
  if (value === null) {
    return (
      <span className="text-muted">
        <span aria-hidden="true">–</span>
        <span className="sr-only">{reason}</span>
        <span className="ml-1 text-xs" aria-hidden="true">
          ({reason})
        </span>
      </span>
    );
  }
  return <span className="tabular-nums">{formatQuantity(value, unit)}</span>;
}
