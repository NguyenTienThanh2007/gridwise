import type { Metadata } from "next";
import { Suspense } from "react";
import { PageHeader } from "@/components/page-header";
import { NewSimulationForm } from "@/components/simulations/new-simulation-form";
import { SimulationTabs } from "@/components/simulations/simulation-tabs";

export const metadata: Metadata = { title: "New simulation" };

export default function Page() {
  return (
    <>
      <PageHeader
        title="Simulations"
        summary="Deterministic power-flow simulations of stored synthetic grids, queued and solved by a separate worker. Results are simulated, not measured."
        tabs={<SimulationTabs current="new" />}
      />
      <Suspense fallback={<p className="text-sm text-muted">Loading…</p>}>
        <NewSimulationForm />
      </Suspense>
    </>
  );
}
