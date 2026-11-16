import Link from "next/link";
import type { ReactNode } from "react";

export interface Crumb {
  href: string;
  label: string;
}

/**
 * The top of every page: where you are, what this is, and what you can do. Tabs, when a page
 * has them, attach to its bottom edge.
 */
export function PageHeader({
  title,
  summary,
  breadcrumbs = [],
  meta,
  actions,
  tabs,
}: {
  title: ReactNode;
  summary?: ReactNode;
  breadcrumbs?: Crumb[];
  /** Small facts beside the title: provenance, version, status. */
  meta?: ReactNode;
  actions?: ReactNode;
  tabs?: ReactNode;
}) {
  return (
    <header className={`mb-6 ${tabs === undefined ? "" : "border-b border-line"}`}>
      {breadcrumbs.length === 0 ? null : (
        <nav aria-label="Breadcrumb" className="mb-1.5">
          <ol className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
            {breadcrumbs.map((crumb) => (
              <li key={crumb.href} className="flex items-center gap-1.5">
                <Link href={crumb.href} className="hover:text-ink hover:underline">
                  {crumb.label}
                </Link>
                <span aria-hidden="true" className="text-subtle">
                  /
                </span>
              </li>
            ))}
          </ol>
        </nav>
      )}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <h1 className="text-page-title">{title}</h1>
            {meta === undefined ? null : (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted">{meta}</div>
            )}
          </div>
          {summary === undefined ? null : (
            <p className="mt-1 max-w-3xl text-sm text-muted">{summary}</p>
          )}
        </div>
        {actions === undefined ? null : (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
      {tabs === undefined ? null : <div className="mt-4">{tabs}</div>}
    </header>
  );
}
