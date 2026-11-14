import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GridListView, PAGE_SIZE } from "@/components/grids/grid-list-view";
import type { ApiFailure, ApiResult } from "@/lib/http/client";
import type { fetchGrids } from "@/lib/resources/grids";
import { type GridPage, decodeGridPage } from "@/lib/resources/grids";
import { FIXTURE_GRID_ID, fixtureGrid, fixtureGridPage } from "@/test/fixtures/grids";

function page(
  items: Record<string, unknown>[],
  total = items.length,
  offset = 0,
): ApiResult<GridPage> {
  const data = decodeGridPage({ ...fixtureGridPage(items, total), offset });
  if (data === null) throw new Error("fixture does not decode");
  return { ok: true, status: 200, data, etag: null, location: null, headers: new Headers() };
}

function failing(failure: ApiFailure): typeof fetchGrids {
  return async () => ({ ok: false, failure });
}

describe("GridListView", () => {
  it("lists grids with their origin, version and counts, linked to their page", async () => {
    render(<GridListView load={async () => page([fixtureGrid()])} />);
    const link = await screen.findByRole("link", { name: "Fixture feeder" });
    expect(link).toHaveAttribute("href", `/grid/${FIXTURE_GRID_ID}`);
    const table = screen.getByRole("table", { name: "Stored grids" });
    expect(table).toHaveTextContent("Synthetic data");
    expect(table).toHaveTextContent("2026-11-14 11:30 UTC");
    expect(screen.getByText("Grids 1–1 of 1")).toBeInTheDocument();
    expect(screen.getByText(/Development mode/)).toBeInTheDocument();
  });

  it("says how to load the demonstration grid when there is none", async () => {
    render(<GridListView load={async () => page([])} />);
    expect(await screen.findByText("No grids are stored yet")).toBeInTheDocument();
    expect(screen.getByText("make seed-demo")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("pages through the list", async () => {
    const load = vi.fn<typeof fetchGrids>(async ({ offset }) =>
      page([fixtureGrid({ name: `Grid at ${offset}` })], PAGE_SIZE + 1, offset),
    );
    render(<GridListView load={load} />);
    await screen.findByText("Grid at 0");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText(`Grid at ${PAGE_SIZE}`);
    expect(load).toHaveBeenLastCalledWith(
      { limit: PAGE_SIZE, offset: PAGE_SIZE },
      expect.anything(),
    );
  });

  it.each<[ApiFailure, string]>([
    [{ kind: "unreachable", message: "No response from the API" }, "The API is unreachable"],
    [{ kind: "not_available" }, "Not available in this environment"],
    [{ kind: "no_tenant" }, "No development organisation is configured"],
    [{ kind: "server", requestId: "req-9" }, "The API reported an internal error"],
    [{ kind: "unexpected", status: 200, message: "bad shape" }, "Unexpected answer from the API"],
  ])("shows its own state for %o", async (failure, title) => {
    render(<GridListView load={failing(failure)} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(title);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("tries again on request", async () => {
    let calls = 0;
    const load: typeof fetchGrids = async () =>
      ++calls === 1
        ? { ok: false, failure: { kind: "unreachable", message: "No response from the API" } }
        : page([fixtureGrid()]);
    render(<GridListView load={load} />);
    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "Fixture feeder" })).toBeInTheDocument(),
    );
  });
});
