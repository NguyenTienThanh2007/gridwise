import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JobsView } from "@/components/simulations/jobs-view";
import type { ApiResult } from "@/lib/http/client";
import { type GridPage, decodeGridPage } from "@/lib/resources/grids";
import { type ScenarioPage, decodeScenarioPage } from "@/lib/resources/scenarios";
import { type JobPage, decodeJobPage, type fetchJobs } from "@/lib/resources/simulations";
import { FIXTURE_GRID_ID, fixtureGrid, fixtureGridPage } from "@/test/fixtures/grids";
import { COMPLETED, FIXTURE_SCENARIO_ID, fixtureJob, fixtureScenario } from "@/test/fixtures/jobs";

const replace = vi.fn((url: string) => window.history.replaceState(null, "", url));
vi.mock("next/navigation", () => ({
  usePathname: () => "/simulations",
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const ok = <T,>(data: T): ApiResult<T> => ({
  ok: true,
  status: 200,
  data,
  etag: null,
  location: null,
  headers: new Headers(),
});
const grids = async () => ok(decodeGridPage(fixtureGridPage([fixtureGrid()])) as GridPage);
const scenarios = async () =>
  ok(
    decodeScenarioPage({
      items: [fixtureScenario()],
      total: 1,
      limit: 100,
      offset: 0,
    }) as ScenarioPage,
  );
const page = (items: Record<string, unknown>[]) =>
  ok(
    decodeJobPage({
      items: items.map(({ attempts: _, ...rest }) => rest),
      total: items.length,
      limit: 25,
      offset: 0,
    }) as JobPage,
  );

beforeEach(() => window.history.replaceState(null, "", "/simulations"));

describe("JobsView", () => {
  it("lists jobs with grid and scenario names and their status in words", async () => {
    const jobs = [
      fixtureJob({
        ...COMPLETED,
        id: "01a1dd8f-0000-7000-8000-0000000000c2",
        scenario: {
          id: FIXTURE_SCENARIO_ID,
          spec_hash: "x",
          specification: {
            schema: "gridwise.scenario/1",
            modifications: [{ type: "scale_loads", factor: 2 }],
          },
        },
      }),
      fixtureJob(),
    ];
    render(<JobsView load={async () => page(jobs)} loadGrids={grids} loadScenarios={scenarios} />);
    const table = await screen.findByRole("table", { name: "Simulation jobs, newest first" });
    expect(table).toHaveTextContent("Completed, converged");
    expect(table).toHaveTextContent("Queued");
    // Two rows name the grid; the third match is the grid filter's option.
    await vi.waitFor(() => expect(table.textContent?.match(/Fixture feeder/g)).toHaveLength(2));
    expect(screen.getByText("Fixture peak")).toBeInTheDocument();
    expect(screen.getByText("Normal operation")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Job 01a1dd8f-0000-7000-8000-0000000000c2" }),
    ).toHaveTextContent("…000000c2");
  });

  it("filters by grid and status, kept in the address", async () => {
    const load = vi.fn<typeof fetchJobs>(async () => page([]));
    render(<JobsView load={load} loadGrids={grids} loadScenarios={scenarios} />);
    expect(await screen.findByText("No simulation has been submitted yet")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "failed" } });
    await vi.waitFor(() =>
      expect(load).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", gridId: null }),
        expect.anything(),
      ),
    );
    await screen.findByRole("option", { name: "Fixture feeder" });
    fireEvent.change(screen.getByLabelText("Grid"), { target: { value: FIXTURE_GRID_ID } });
    await vi.waitFor(() =>
      expect(load).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: "failed", gridId: FIXTURE_GRID_ID }),
        expect.anything(),
      ),
    );
    expect(window.location.search).toBe(`?status=failed&grid=${FIXTURE_GRID_ID}`);
    expect(await screen.findByText("No job matches these filters")).toBeInTheDocument();
  });

  it("refreshes only on request", async () => {
    const load = vi.fn<typeof fetchJobs>(async () => page([fixtureJob()]));
    render(<JobsView load={load} loadGrids={grids} loadScenarios={scenarios} />);
    await screen.findByRole("table");
    expect(load).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
  });
});
