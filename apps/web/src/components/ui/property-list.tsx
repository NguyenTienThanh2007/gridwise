import type { ReactNode } from "react";

/** Label and value pairs: one layout for metadata, inspectors and job details. */
export function PropertyList({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <dl className={`divide-y divide-line ${className}`}>{children}</dl>;
}

export function Property({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(7rem,38%)_minmax(0,1fr)] gap-x-4 py-1.5">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}
