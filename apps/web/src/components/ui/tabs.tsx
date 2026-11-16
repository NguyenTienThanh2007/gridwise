import Link from "next/link";

export interface Tab {
  href: string;
  label: string;
}

/** Sections of one page, each with its own address, attached under the page header. */
export function Tabs({ label, tabs, current }: { label: string; tabs: Tab[]; current: string }) {
  return (
    <nav aria-label={label} className="-mb-px overflow-x-auto">
      <ul className="flex gap-0.5">
        {tabs.map((tab) => {
          const active = tab.href === current;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={`block whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors duration-100 ${
                  active ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
                }`}
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
