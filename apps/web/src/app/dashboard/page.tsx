import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";
import { SystemStatusCard } from "@/components/system-status";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        summary="Platform status. Grid KPIs appear here once telemetry (P2) and analytics (P3) exist; until then no grid figures are shown."
      />
      <SystemStatusCard />
    </>
  );
}
