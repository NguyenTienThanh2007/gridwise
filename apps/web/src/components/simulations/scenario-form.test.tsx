import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScenarioForm } from "@/components/simulations/scenario-form";
import { type Scenario, type createScenario, decodeScenario } from "@/lib/resources/scenarios";
import { fixtureScenario } from "@/test/fixtures/jobs";

const created = {
  ok: true as const,
  status: 201,
  data: decodeScenario(fixtureScenario()) as Scenario,
  etag: null,
  location: null,
  headers: new Headers(),
};

describe("ScenarioForm", () => {
  it("creates a scenario from the changes as written", async () => {
    const create = vi.fn<typeof createScenario>(async () => created);
    const onCreated = vi.fn();
    render(<ScenarioForm create={create} onCreated={onCreated} />);
    expect(screen.queryByRole("button", { name: /Remove change/ })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Peak" } });
    fireEvent.change(screen.getByLabelText("Factor"), { target: { value: "1.3" } });
    fireEvent.click(screen.getByRole("button", { name: "Add change" }));
    fireEvent.change(screen.getAllByLabelText("Kind of change")[1] as HTMLElement, {
      target: { value: "set_switch" },
    });
    fireEvent.change(screen.getByLabelText("Switch key"), { target: { value: "switch-1" } });
    fireEvent.click(screen.getByRole("radio", { name: "Closed" }));
    fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));
    await vi.waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(create).toHaveBeenCalledWith({
      name: "Peak",
      description: "",
      modifications: [
        { type: "scale_loads", factor: 1.3, keys: null },
        { type: "set_switch", key: "switch-1", closed: true },
      ],
    });
    expect(screen.getByLabelText("Name")).toHaveValue("");
  });

  it("checks every change before sending anything", () => {
    const create = vi.fn<typeof createScenario>();
    render(<ScenarioForm create={create} onCreated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Factor"), { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(/Enter a name/);
    expect(screen.getByLabelText("Factor")).toHaveAccessibleDescription(/at most 100/);
    expect(create).not.toHaveBeenCalled();
  });

  it("shows the engine's reasons under the change they concern, and a taken name under the name", async () => {
    const create = vi
      .fn<typeof createScenario>()
      .mockResolvedValueOnce({
        ok: false,
        failure: {
          kind: "invalid",
          status: 422,
          code: "scenario_invalid",
          message: "x",
          details: [
            {
              location: ["body", "modifications", 0],
              message: "keys must be a non-empty list",
              type: "invalid_scenario_key",
            },
          ],
        },
      })
      .mockResolvedValueOnce({
        ok: false,
        failure: {
          kind: "conflict",
          status: 409,
          code: "scenario_name_conflict",
          message: "x",
          details: [],
          currentVersion: null,
        },
      });
    render(<ScenarioForm create={create} onCreated={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Peak" } });
    fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));
    expect(
      await screen.findByText("keys must be a non-empty list (invalid_scenario_key)"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create scenario" }));
    expect(await screen.findByText("Another scenario already has this name.")).toBeInTheDocument();
  });
});
