import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScenariosView } from "@/components/simulations/scenarios-view";
import {
  type ScenarioPage,
  decodeScenarioPage,
  type deleteScenario,
} from "@/lib/resources/scenarios";
import { FIXTURE_SCENARIO_ID, fixtureScenario } from "@/test/fixtures/jobs";

const list = async () => ({
  ok: true as const,
  status: 200,
  data: decodeScenarioPage({
    items: [fixtureScenario()],
    total: 1,
    limit: 100,
    offset: 0,
  }) as ScenarioPage,
  etag: null,
  location: null,
  headers: new Headers(),
});

describe("ScenariosView", () => {
  it("lists scenarios with their changes and a link to simulate with them", async () => {
    render(<ScenariosView load={list} />);
    expect(
      await screen.findByRole("heading", { level: 3, name: "Fixture peak" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Take line l1 out of service")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Simulate with this scenario" })).toHaveAttribute(
      "href",
      `/simulations/new?scenario=${FIXTURE_SCENARIO_ID}`,
    );
  });

  it("deletes only after confirmation", async () => {
    const remove = vi.fn<typeof deleteScenario>(async () => ({
      ok: true,
      status: 204,
      data: true,
      etag: null,
      location: null,
      headers: new Headers(),
    }));
    render(<ScenariosView load={list} remove={remove} />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete scenario Fixture peak" }));
    expect(screen.getByText(/Jobs that used it keep their own copy/)).toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await vi.waitFor(() => expect(remove).toHaveBeenCalledWith(FIXTURE_SCENARIO_ID));
  });

  it("says what a simulation does without a scenario", async () => {
    render(
      <ScenariosView
        load={async () => ({
          ...(await list()),
          data: { items: [], total: 0, limit: 100, offset: 0 },
        })}
      />,
    );
    expect(await screen.findByText("No scenario is stored yet")).toBeInTheDocument();
  });
});
