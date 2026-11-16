export type Phase = "P0" | "P1" | "P2" | "P3" | "P4" | "P5" | "P6";

export interface NavItem {
  href: string;
  label: string;
  /** Roadmap phase that delivers the route's real content. */
  phase: Phase;
  summary: string;
  /** Working sections first; sections that are still placeholders are grouped as planned. */
  group: "workspace" | "planned";
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    phase: "P0",
    summary: "Platform status today; grid KPIs once telemetry and analytics exist.",
    group: "workspace",
  },
  {
    href: "/grid",
    label: "Grids",
    phase: "P1",
    summary: "Stored grid models, their network and assets (2D); the 3D twin follows in P5.",
    group: "workspace",
  },
  {
    href: "/simulations",
    label: "Simulations",
    phase: "P1",
    summary:
      "Queue power-flow simulations of stored grids, with or without a scenario, and follow them.",
    group: "workspace",
  },
  {
    href: "/assets",
    label: "Assets",
    phase: "P1",
    summary:
      "Each grid's buses, lines, transformers, loads, generators, external grids and switches.",
    group: "workspace",
  },
  {
    href: "/monitoring",
    label: "Monitoring",
    phase: "P2",
    summary: "Live telemetry with explicit data-quality flags.",
    group: "planned",
  },
  {
    href: "/analytics",
    label: "Analytics",
    phase: "P3",
    summary: "Energy, loading and asset-performance KPIs from the gold layer.",
    group: "planned",
  },
  {
    href: "/forecasting",
    label: "Forecasting",
    phase: "P4",
    summary: "Load forecasts with their backtest metrics and model metadata.",
    group: "planned",
  },
  {
    href: "/alerts",
    label: "Alerts",
    phase: "P2",
    summary: "Grid events, limit violations and anomaly alerts.",
    group: "planned",
  },
  {
    href: "/settings",
    label: "Settings",
    phase: "P6",
    summary: "Organisation, members, roles and audit log.",
    group: "planned",
  },
];

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
