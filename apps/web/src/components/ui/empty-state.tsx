import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <section className="max-w-3xl rounded-lg border border-dashed border-line bg-panel p-6">
      <p className="font-medium">{title}</p>
      {children === undefined ? null : <div className="mt-2 text-sm text-muted">{children}</div>}
    </section>
  );
}
