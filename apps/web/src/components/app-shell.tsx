"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { NAV_ITEMS, isActive } from "@/lib/navigation";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded focus:bg-panel focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <aside className="bg-rail text-rail-ink md:w-56 md:shrink-0">
        <div className="px-5 py-4 text-lg font-semibold tracking-wide text-white">GRIDWISE</div>
        <nav aria-label="Primary">
          <ul className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
            {NAV_ITEMS.map((item) => {
              const active = isActive(pathname, item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`block whitespace-nowrap rounded px-3 py-2 text-sm ${
                      active ? "bg-white/15 font-medium text-white" : "hover:bg-white/10"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-line bg-panel px-6 py-3">
          <p className="text-sm text-muted">Smart grid digital twin</p>
          <p
            className="rounded-full border border-warn/40 bg-warn/10 px-3 py-1 text-xs font-medium text-warn"
            title="GRIDWISE does not control real grid equipment. All data in this build is simulated or absent."
          >
            Simulation and decision support only
          </p>
        </header>
        <main id="main" className="flex-1 px-6 py-6">
          {children}
        </main>
      </div>
    </div>
  );
}
