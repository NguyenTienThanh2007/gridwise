import { Tabs } from "@/components/ui/tabs";

export type SimulationSection = "jobs" | "new" | "scenarios";

const HREF: Record<SimulationSection, string> = {
  jobs: "/simulations",
  new: "/simulations/new",
  scenarios: "/simulations/scenarios",
};

export function SimulationTabs({ current }: { current: SimulationSection }) {
  return (
    <Tabs
      label="Simulation sections"
      current={HREF[current]}
      tabs={[
        { href: HREF.jobs, label: "Jobs" },
        { href: HREF.new, label: "New simulation" },
        { href: HREF.scenarios, label: "Scenarios" },
      ]}
    />
  );
}
