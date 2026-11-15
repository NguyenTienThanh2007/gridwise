import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GridSettings } from "@/components/grids/grid-settings";
import type { ApiResult } from "@/lib/http/client";
import type { updateGrid } from "@/lib/resources/assets";
import { type Grid, decodeGrid } from "@/lib/resources/grids";
import { fixtureGrid } from "@/test/fixtures/grids";

const grid = decodeGrid(fixtureGrid()) as Grid;

function setup(
  update = vi.fn<typeof updateGrid>(
    async () =>
      ({
        ok: true,
        status: 200,
        data: { ...grid, version: 4 },
        etag: 4,
        location: null,
        headers: new Headers(),
      }) as ApiResult<Grid>,
  ),
) {
  const onSaved = vi.fn();
  render(<GridSettings grid={grid} onSaved={onSaved} update={update} />);
  return { update, onSaved };
}

describe("GridSettings", () => {
  it("sends only the changed field with the version on screen", async () => {
    const { update, onSaved } = setup();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "New text" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved. The grid is now version 4.")).toBeInTheDocument();
    expect(update).toHaveBeenCalledWith(grid.id, { description: "New text" }, 3);
    expect(onSaved).toHaveBeenCalled();
  });

  it("checks the limits and counts characters", () => {
    setup();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: " " } });
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription(/Enter a name/);
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "x".repeat(2001) } });
    expect(screen.getByText("2001 / 2000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("shows a name conflict under the name", async () => {
    setup(
      vi.fn<typeof updateGrid>(async () => ({
        ok: false,
        failure: {
          kind: "conflict",
          status: 409,
          code: "grid_name_conflict",
          message: "taken",
          details: [],
          currentVersion: null,
        },
      })),
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Taken" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Another grid already has this name.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
  });

  it("explains a stale version and keeps the draft", async () => {
    setup(
      vi.fn<typeof updateGrid>(async () => ({
        ok: false,
        failure: {
          kind: "conflict",
          status: 412,
          code: "version_conflict",
          message: "x",
          details: [],
          currentVersion: 5,
        },
      })),
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mine" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("It is now version 5");
    expect(screen.getByLabelText("Name")).toHaveValue("Mine");
  });
});
