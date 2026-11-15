import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AssetEditForm } from "@/components/assets/asset-edit-form";
import type { ApiFailure, ApiResult } from "@/lib/http/client";
import type { AssetResponse, updateAsset } from "@/lib/resources/assets";
import { feeder } from "@/test/fixtures/networks";

const GRID = "0a0a0a0a-0000-4000-8000-0000000000f1";
const net = feeder();
function required<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("fixture is missing an element");
  return value;
}
const lineAb = required(net.lines[0]);
const openSwitch = required(net.switches.find((s) => s.key === "s-bc"));

function saved(version: number): ApiResult<AssetResponse> {
  return {
    ok: true,
    status: 200,
    data: { gridId: GRID, gridVersion: version, topologyHash: "x", type: "lines", asset: lineAb },
    etag: version,
    location: null,
    headers: new Headers(),
  };
}

function setup(
  element = lineAb as typeof lineAb | typeof openSwitch,
  update = vi.fn<typeof updateAsset>(async () => saved(4)),
) {
  const handlers = { onSaved: vi.fn(), onCancel: vi.fn(), onReload: vi.fn() };
  const type = "closed" in element ? "switches" : "lines";
  render(
    <AssetEditForm
      gridId={GRID}
      version={3}
      target={{ type, key: element.key }}
      element={element}
      update={update}
      {...handlers}
    />,
  );
  return { update, ...handlers };
}

const save = () => screen.getByRole("button", { name: /Save|Review change|Confirm and save/ });

describe("AssetEditForm", () => {
  it("offers only the name and the service state for a line", () => {
    setup();
    expect(screen.getByLabelText("Name")).toHaveValue("Line l-ab");
    expect(screen.getByRole("group", { name: "Service state" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Model position" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/length|resistance|power/i)).not.toBeInTheDocument();
  });

  it("offers only the name and the model position for a switch", () => {
    setup(openSwitch);
    expect(screen.getByRole("group", { name: "Model position" })).toHaveAccessibleDescription(
      /not a command to any equipment/,
    );
    expect(screen.queryByRole("group", { name: "Service state" })).not.toBeInTheDocument();
  });

  it("keeps Save disabled until something changes, and Cancel sends nothing", () => {
    const { update, onCancel } = setup();
    expect(save()).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
  });

  it.each([
    ["", "Enter a name."],
    ["   ", "Enter a name."],
    ["x".repeat(201), "Use at most 200 characters."],
  ])("refuses the name %j", (value, message) => {
    setup();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value } });
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(new RegExp(message));
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(save()).toBeDisabled();
  });

  it("saves a rename with the opened version, sending only the name", async () => {
    const { update, onSaved } = setup();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Feeder A–B" } });
    fireEvent.click(save());
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalledWith(4));
    expect(update).toHaveBeenCalledWith(
      GRID,
      "lines",
      "l-ab",
      { kind: "element", name: "Feeder A–B" },
      3,
    );
  });

  it("reviews a switch position change before saving it", async () => {
    const { update, onSaved } = setup(openSwitch);
    fireEvent.click(screen.getByRole("radio", { name: "Closed" }));
    fireEvent.click(screen.getByRole("button", { name: "Review change" }));
    expect(update).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Sets Switch s-bc to closed in the stored simulation model only. Nothing is sent to any equipment.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm and save" }));
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(update).toHaveBeenCalledWith(
      GRID,
      "switches",
      "s-bc",
      { kind: "switch", closed: true },
      3,
    );
  });

  it("keeps the draft on a stale version, never resends, and saves again with the new one", async () => {
    const conflict: ApiFailure = {
      kind: "conflict",
      status: 412,
      code: "version_conflict",
      message: "changed",
      details: [],
      currentVersion: 7,
    };
    const update = vi
      .fn<typeof updateAsset>()
      .mockResolvedValueOnce({ ok: false, failure: conflict })
      .mockResolvedValueOnce(saved(8));
    const { onReload, onSaved } = setup(lineAb, update);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(save());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("It is now version 7");
    expect(alert).toHaveTextContent("nothing was overwritten");
    expect(screen.getByLabelText("Name")).toHaveValue("Renamed");
    expect(update).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Reload and review" }));
    expect(onReload).toHaveBeenCalled();
    expect(update).toHaveBeenCalledTimes(1);
    fireEvent.click(save());
    await vi.waitFor(() => expect(onSaved).toHaveBeenCalledWith(8));
    expect(update).toHaveBeenLastCalledWith(
      GRID,
      "lines",
      "l-ab",
      { kind: "element", name: "Renamed" },
      7,
    );
  });

  it("shows the engine's reasons when the grid would not be valid", async () => {
    const update = vi.fn<typeof updateAsset>(async () => ({
      ok: false,
      failure: {
        kind: "invalid",
        status: 422,
        code: "grid_validation_failed",
        message: "invalid",
        details: [
          {
            location: ["grid"],
            message: "The grid has no in-service external grid",
            type: "missing_external_grid",
          },
        ],
      },
    }));
    setup(lineAb, update);
    fireEvent.click(screen.getByRole("radio", { name: "Out of service" }));
    fireEvent.click(save());
    fireEvent.click(save());
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Not saved: the grid would not be valid");
    expect(alert).toHaveTextContent("missing_external_grid");
    expect(screen.getByRole("radio", { name: "Out of service" })).toBeChecked();
  });

  it("keeps the draft when the API cannot be reached", async () => {
    setup(
      lineAb,
      vi.fn<typeof updateAsset>(async () => ({
        ok: false,
        failure: { kind: "unreachable", message: "No response from the API" },
      })),
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(save());
    expect(await screen.findByRole("alert")).toHaveTextContent("Your change is kept in the form.");
    expect(screen.getByLabelText("Name")).toHaveValue("Renamed");
  });
});
