import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GridDetailView } from "@/components/grids/grid-detail-view";
import type { ApiResult } from "@/lib/http/client";
import type { fetchGrid } from "@/lib/resources/grids";
import { type Grid, decodeGrid } from "@/lib/resources/grids";
import { FIXTURE_GRID_ID, fixtureGrid } from "@/test/fixtures/grids";

vi.mock("next/navigation", () => ({
  usePathname: () => "/grid/x",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

/** The network loads separately; these tests are about the grid's own details. */
const pendingTopology = () => new Promise<never>(() => undefined);

function found(overrides: Record<string, unknown> = {}): ApiResult<Grid> {
  const data = decodeGrid(fixtureGrid(overrides));
  if (data === null) throw new Error("fixture does not decode");
  return {
    ok: true,
    status: 200,
    data,
    etag: data.version,
    location: null,
    headers: new Headers(),
  };
}

describe("GridDetailView", () => {
  it("shows the stored model's metadata, labelled synthetic", async () => {
    render(
      <GridDetailView
        loadTopology={pendingTopology}
        id={FIXTURE_GRID_ID}
        load={async () => found()}
      />,
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "Fixture feeder" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    expect(screen.getByText("Unit-test fixture, not a real network.")).toBeInTheDocument();
    const hash = screen.getByTitle("ab".repeat(32));
    expect(hash).toHaveTextContent("abababababab…");
    expect(screen.getByText("50 Hz")).toBeInTheDocument();
    const elements = screen.getByRole("table", { name: "Elements by type" });
    expect(elements).toHaveTextContent("External grids1");
    expect(screen.getByText(/Development mode/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Network" })).toBeInTheDocument();
  });

  it("makes no request for an id that cannot be a grid", async () => {
    const load = vi.fn<typeof fetchGrid>();
    render(<GridDetailView loadTopology={pendingTopology} id="demo-feeder" load={load} />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Grid not found" }),
    ).toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });

  it("says when the grid does not exist or is another organisation's", async () => {
    render(
      <GridDetailView
        id={FIXTURE_GRID_ID}
        load={async () => ({
          ok: false,
          failure: { kind: "not_found", code: "grid_not_found", message: "Grid not found" },
        })}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The grid does not exist, or it belongs to another organisation.",
    );
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("omits an empty description", async () => {
    render(
      <GridDetailView
        loadTopology={pendingTopology}
        id={FIXTURE_GRID_ID}
        load={async () => found({ description: "" })}
      />,
    );
    await screen.findByRole("heading", { level: 1, name: "Fixture feeder" });
    expect(screen.queryByText("Unit-test fixture, not a real network.")).not.toBeInTheDocument();
  });
});
