import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  NewSimulationForm,
  iterationsError,
  toleranceError,
} from "@/components/simulations/new-simulation-form";
import type { ApiResult } from "@/lib/http/client";
import { type GridPage, decodeGridPage } from "@/lib/resources/grids";
import { type ScenarioPage, decodeScenarioPage } from "@/lib/resources/scenarios";
import { type Job, decodeJob, type submitSimulation } from "@/lib/resources/simulations";
import { FIXTURE_GRID_ID, fixtureGrid, fixtureGridPage } from "@/test/fixtures/grids";
import {
  FIXTURE_JOB_ID,
  FIXTURE_SCENARIO_ID,
  fixtureJob,
  fixtureScenario,
} from "@/test/fixtures/jobs";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
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
const queued = ok(decodeJob(fixtureJob()) as Job);

function form(submit: typeof submitSimulation) {
  render(<NewSimulationForm submit={submit} loadGrids={grids} loadScenarios={scenarios} />);
}

describe("solver option rules", () => {
  it("follow the engine's bounds", () => {
    expect(toleranceError("1e-8")).toBeNull();
    expect(toleranceError("0.001")).toBeNull();
    expect(toleranceError("0")).not.toBeNull();
    expect(toleranceError("0.01")).not.toBeNull();
    expect(toleranceError("x")).not.toBeNull();
    expect(iterationsError("10")).toBeNull();
    expect(iterationsError("0")).not.toBeNull();
    expect(iterationsError("101")).not.toBeNull();
    expect(iterationsError("2.5")).not.toBeNull();
  });
});

describe("NewSimulationForm", () => {
  it("queues the grid version on screen with a scenario, then opens the job", async () => {
    const submit = vi.fn<typeof submitSimulation>(async () => queued);
    form(submit);
    expect(await screen.findByText(/Simulates version/)).toHaveTextContent(
      "Simulates version 3 exactly.",
    );
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Scenario"), { target: { value: FIXTURE_SCENARIO_ID } });
    expect(screen.getByText("Set switch s1 to closed (model position)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Queue simulation" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith(`/simulations/${FIXTURE_JOB_ID}`));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({
        gridId: FIXTURE_GRID_ID,
        gridVersion: 3,
        scenarioId: FIXTURE_SCENARIO_ID,
        configuration: null,
      }),
    );
  });

  it("retries the same request with the same key, and a changed one with a new key", async () => {
    const submit = vi
      .fn<typeof submitSimulation>()
      .mockResolvedValueOnce({
        ok: false,
        failure: { kind: "unreachable", message: "No response from the API" },
      })
      .mockResolvedValueOnce({
        ok: false,
        failure: { kind: "unreachable", message: "No response from the API" },
      })
      .mockResolvedValue(queued);
    form(submit);
    const button = await screen.findByRole("button", { name: "Queue simulation" });
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent("Submitting again is safe");
    fireEvent.click(button);
    await vi.waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
    const [first, second] = submit.mock.calls.map(([input]) => input.idempotencyKey);
    expect(second).toBe(first);
    fireEvent.change(screen.getByLabelText("Maximum iterations"), { target: { value: "20" } });
    fireEvent.click(button);
    await vi.waitFor(() => expect(submit).toHaveBeenCalledTimes(3));
    expect(submit.mock.calls[2]?.[0].idempotencyKey).not.toBe(first);
    expect(submit.mock.calls[2]?.[0].configuration).toEqual({
      toleranceMva: 1e-8,
      maxIterations: 20,
    });
  });

  it("refuses options outside the engine's bounds", async () => {
    form(vi.fn());
    fireEvent.change(await screen.findByLabelText("Tolerance (MVA)"), { target: { value: "2" } });
    expect(screen.getByLabelText("Tolerance (MVA)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Queue simulation" })).toBeDisabled();
  });

  it("asks for a review when the grid changed", async () => {
    form(async () => ({
      ok: false,
      failure: {
        kind: "conflict",
        status: 412,
        code: "version_conflict",
        message: "x",
        details: [],
        currentVersion: 4,
      },
    }));
    fireEvent.click(await screen.findByRole("button", { name: "Queue simulation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The grid is now version 4.");
  });

  it("explains a scenario that does not fit the grid", async () => {
    form(async () => ({
      ok: false,
      failure: {
        kind: "invalid",
        status: 422,
        code: "scenario_not_applicable",
        message: "names elements",
        details: [
          {
            location: ["body", "modifications", 3],
            message: "no switch s1",
            type: "scenario_key_not_found",
          },
        ],
      },
    }));
    fireEvent.click(await screen.findByRole("button", { name: "Queue simulation" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Not queued: the scenario names elements this grid does not have",
    );
    expect(alert).toHaveTextContent("scenario_key_not_found");
  });
});
