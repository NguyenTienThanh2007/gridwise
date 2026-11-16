import type { Metadata } from "next";
import { PageHeader } from "@/components/page-header";
import { ScenariosView } from "@/components/simulations/scenarios-view";
import { SimulationTabs } from "@/components/simulations/simulation-tabs";

export const metadata: Metadata = { title: "Scenarios" };

export default function Page() {
  return (
    <>
      <PageHeader
        title="Simulations"
        summary="Deterministic power-flow simulations of stored synthetic grids, queued and solved by a separate worker. Results are simulated, not measured."
        tabs={<SimulationTabs current="scenarios" />}
      />
      <ScenariosView />
    </>
  );
}
