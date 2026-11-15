import Link from "next/link";

export interface Tab {
  href: string;
  label: string;
}

/** Sections of one page, each with its own address. The current one is marked for AT. */
export function Tabs({ label, tabs, current }: { label: string; tabs: Tab[]; current: string }) {
  return (
    <nav aria-label={label} className="mb-6 border-b border-line">
      <ul className="flex gap-1">
        {tabs.map((tab) => {
          const active = tab.href === current;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={`-mb-px block border-b-2 px-3 py-2 text-sm ${
                  active
                    ? "border-accent font-medium text-accent"
                    : "border-transparent text-muted hover:text-ink"
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
