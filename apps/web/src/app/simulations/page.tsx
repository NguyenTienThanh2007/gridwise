import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/page-header";
import { JobsView } from "@/components/simulations/jobs-view";
import { SimulationTabs } from "@/components/simulations/simulation-tabs";

export const metadata: Metadata = { title: "Simulations" };

export default function Page() {
  return (
    <>
      <PageHeader
        title="Simulations"
        summary="Deterministic power-flow simulations of stored synthetic grids, queued and solved by a separate worker. Results are simulated, not measured."
        tabs={<SimulationTabs current="jobs" />}
      />
      <Suspense fallback={<p className="text-sm text-muted">Loading jobs…</p>}>
        <JobsView />
      </Suspense>
    </>
  );
}
