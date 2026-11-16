import { type ReactNode, useId } from "react";

/**
 * A titled part of a page. No box: hierarchy comes from the title, spacing and alignment.
 * Use `Panel` only where a boundary means something (an inspector, a form, a canvas).
 */
export function Section({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={className}>
      <div className="mb-2 flex min-h-7 flex-wrap items-center justify-between gap-x-4 gap-y-1">
        <div>
          <h2 id={id} className="text-section-title">
            {title}
          </h2>
          {description === undefined ? null : (
            <p className="mt-0.5 text-xs text-muted">{description}</p>
          )}
        </div>
        {actions === undefined ? null : <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function Panel({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={`rounded-panel border border-line bg-panel ${padded ? "p-4" : ""} ${className}`}
    >
      {children}
    </div>
  );
}
