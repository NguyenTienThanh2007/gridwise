export type Phase = "P0" | "P1" | "P2" | "P3" | "P4" | "P5" | "P6";

export interface NavItem {
  href: string;
  label: string;
  /** Roadmap phase that delivers the route's real content. */
  phase: Phase;
  summary: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    phase: "P0",
    summary: "Platform status today; grid KPIs once telemetry and analytics exist.",
  },
  {
    href: "/grid",
    label: "Grid",
    phase: "P1",
    summary: "Network topology from the grid engine, then the interactive 3D twin (P5).",
  },
  {
    href: "/monitoring",
    label: "Monitoring",
    phase: "P2",
    summary: "Live telemetry with explicit data-quality flags.",
  },
  {
    href: "/analytics",
    label: "Analytics",
    phase: "P3",
    summary: "Energy, loading and asset-performance KPIs from the gold layer.",
  },
  {
    href: "/forecasting",
    label: "Forecasting",
    phase: "P4",
    summary: "Load forecasts with their backtest metrics and model metadata.",
  },
  {
    href: "/simulations",
    label: "Simulations",
    phase: "P1",
    summary: "Deterministic power-flow scenarios and their results.",
  },
  {
    href: "/alerts",
    label: "Alerts",
    phase: "P2",
    summary: "Grid events, limit violations and anomaly alerts.",
  },
  {
    href: "/assets",
    label: "Assets",
    phase: "P1",
    summary: "Transformers, lines, generators, loads, storage, meters and sensors.",
  },
  {
    href: "/settings",
    label: "Settings",
    phase: "P6",
    summary: "Organisation, members, roles and audit log.",
  },
];

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
