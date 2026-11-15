import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DeleteGrid } from "@/components/grids/delete-grid";
import type { deleteGrid } from "@/lib/resources/assets";
import { type Grid, decodeGrid } from "@/lib/resources/grids";
import { fixtureGrid } from "@/test/fixtures/grids";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const grid = decodeGrid(fixtureGrid()) as Grid;

describe("DeleteGrid", () => {
  it("explains what is lost and kept, and needs the exact name", () => {
    const remove = vi.fn<typeof deleteGrid>();
    render(<DeleteGrid grid={grid} onReload={vi.fn()} remove={remove} />);
    expect(screen.getByText(/This cannot be undone/)).toBeInTheDocument();
    expect(screen.getByText(/Simulation jobs keep their own copies/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Delete grid permanently" });
    const input = screen.getByLabelText(/Type the grid's name to confirm/);
    expect(button).toBeDisabled();
    fireEvent.change(input, { target: { value: "fixture feeder" } });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(remove).not.toHaveBeenCalled();
  });

  it("deletes with the version on screen, then returns to the grid list", async () => {
    const remove = vi.fn<typeof deleteGrid>(async () => ({
      ok: true,
      status: 204,
      data: true,
      etag: null,
      location: null,
      headers: new Headers(),
    }));
    render(<DeleteGrid grid={grid} onReload={vi.fn()} remove={remove} />);
    fireEvent.change(screen.getByLabelText(/Type the grid's name/), {
      target: { value: "Fixture feeder" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete grid permanently" }));
    await vi.waitFor(() => expect(push).toHaveBeenCalledWith("/grid?deleted=1"));
    expect(remove).toHaveBeenCalledWith(grid.id, 3);
  });

  it("deletes nothing when the grid changed meanwhile", async () => {
    const onReload = vi.fn();
    render(
      <DeleteGrid
        grid={grid}
        onReload={onReload}
        remove={async () => ({
          ok: false,
          failure: {
            kind: "conflict",
            status: 412,
            code: "version_conflict",
            message: "x",
            details: [],
            currentVersion: 6,
          },
        })}
      />,
    );
    fireEvent.change(screen.getByLabelText(/Type the grid's name/), {
      target: { value: "Fixture feeder" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Delete grid permanently" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("It is now version 6");
    fireEvent.click(screen.getByRole("button", { name: "Reload and review" }));
    expect(onReload).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete grid permanently" })).toBeDisabled();
  });

  it("tells how to recreate the demonstration grid", () => {
    render(
      <DeleteGrid
        grid={{ ...grid, id: "d0000000-0000-4000-8000-000000000002" }}
        onReload={vi.fn()}
      />,
    );
    expect(screen.getByText("make seed-demo")).toBeInTheDocument();
  });
});
