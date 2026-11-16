import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="max-w-3xl rounded-panel border border-line bg-sunken/60 px-4 py-5">
      <p className="text-label">{title}</p>
      {children === undefined ? null : <div className="mt-1.5 text-sm text-muted">{children}</div>}
    </section>
  );
}
