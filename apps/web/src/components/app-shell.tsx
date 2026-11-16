"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { DevTenantNotice } from "@/components/ui/dev-tenant-notice";
import {
  AssetsIcon,
  CloseIcon,
  DashboardIcon,
  GridIcon,
  MarkIcon,
  MenuIcon,
  SimulationIcon,
} from "@/components/ui/icons";
import { NAV_ITEMS, type NavItem, isActive } from "@/lib/navigation";

const ICONS: Record<string, () => ReactNode> = {
  "/dashboard": DashboardIcon,
  "/grid": GridIcon,
  "/simulations": SimulationIcon,
  "/assets": AssetsIcon,
};

const SAFETY =
  "GRIDWISE does not control real grid equipment. All data in this build is simulated or absent.";

function Brand() {
  return (
    <Link href="/dashboard" className="flex items-center gap-2.5 text-white">
      <MarkIcon />
      <span className="text-[0.9375rem] font-semibold tracking-[0.08em]">GRIDWISE</span>
    </Link>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const link = (item: NavItem) => {
    const active = isActive(pathname, item.href);
    const Icon = ICONS[item.href];
    return (
      <li key={item.href}>
        <Link
          href={item.href}
          onClick={onNavigate}
          aria-current={active ? "page" : undefined}
          className={`flex h-8 items-center gap-2.5 rounded-control px-2.5 text-sm transition-colors duration-100 ${
            active
              ? "bg-white/10 font-medium text-white shadow-[inset_2px_0_0_var(--color-accent)]"
              : item.group === "planned"
                ? "text-rail-ink/70 hover:bg-white/5 hover:text-rail-ink"
                : "text-rail-ink hover:bg-white/5 hover:text-white"
          }`}
        >
          {Icon === undefined ? null : <Icon />}
          <span className="flex-1">{item.label}</span>
          {item.group === "planned" ? (
            <>
              <span aria-hidden="true" className="text-[0.625rem] tracking-wide text-rail-ink/50">
                {item.phase}
              </span>
              <span className="sr-only">, planned for {item.phase}</span>
            </>
          ) : null}
        </Link>
      </li>
    );
  };
  return (
    <nav aria-label="Primary" className="flex flex-col gap-5">
      <ul className="flex flex-col gap-0.5">
        {NAV_ITEMS.filter((item) => item.group === "workspace").map(link)}
      </ul>
      <div>
        <p className="mb-1 px-2.5 text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-rail-ink/50">
          Planned
        </p>
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.filter((item) => item.group === "planned").map(link)}
        </ul>
      </div>
    </nav>
  );
}

/**
 * The application frame: a navigation rail (a drawer below 1024 px), and above every page one
 * strip that states what this build is: simulation and decision support only, in development
 * mode for a fixed organisation.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    // Focus the first section, not the logo.
    drawer.current?.querySelector<HTMLElement>("nav a")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        menuButton.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div className="min-h-screen lg:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-control focus:bg-panel focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <aside className="hidden w-[216px] shrink-0 border-r border-rail-line bg-rail lg:block">
        <div className="sticky top-0 flex h-screen flex-col gap-6 overflow-y-auto px-3 py-4">
          <div className="px-2.5">
            <Brand />
          </div>
          <NavLinks />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center gap-3 bg-rail px-4 lg:hidden">
          <button
            ref={menuButton}
            type="button"
            aria-expanded={open}
            aria-controls="navigation-drawer"
            aria-label={open ? "Close navigation" : "Open navigation"}
            onClick={() => setOpen((value) => !value)}
            className="-ml-1.5 flex h-8 w-8 items-center justify-center rounded-control text-rail-ink hover:bg-white/10 hover:text-white"
          >
            {open ? <CloseIcon /> : <MenuIcon />}
          </button>
          <Brand />
        </header>

        <div className="flex flex-col gap-x-4 gap-y-0.5 border-b border-line bg-sunken px-4 py-1.5 text-xs text-muted lg:flex-row lg:items-baseline lg:px-6">
          <p className="shrink-0" title={SAFETY}>
            <span
              className="mr-1.5 inline-block h-2 w-2 rounded-[1px] bg-warn align-[0.05em]"
              aria-hidden="true"
            />
            <span className="font-medium text-ink">Simulation and decision support only</span>
            <span className="sr-only">. {SAFETY}</span>
          </p>
          <DevTenantNotice />
        </div>

        <main id="main" className="flex-1 px-4 py-6 lg:px-8">
          <div className="mx-auto w-full max-w-[1440px]">{children}</div>
        </main>
      </div>

      {open ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            tabIndex={-1}
            onClick={close}
            className="absolute inset-0 bg-ink/40"
          />
          <div
            id="navigation-drawer"
            ref={drawer}
            className="absolute inset-y-0 left-0 flex w-[264px] max-w-[85vw] flex-col gap-6 overflow-y-auto bg-rail px-3 py-4"
          >
            <div className="flex items-center justify-between px-2.5">
              <Brand />
            </div>
            <NavLinks onNavigate={close} />
          </div>
        </div>
      ) : null}
    </div>
  );
}
