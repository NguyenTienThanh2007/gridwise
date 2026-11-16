import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GridWorkspace } from "@/components/grids/grid-workspace";
import type { ApiFailure, ApiResult } from "@/lib/http/client";
import { type Grid, decodeGrid, type fetchGrid } from "@/lib/resources/grids";
import type { Topology } from "@/lib/resources/topology";
import { FIXTURE_GRID_ID, fixtureGrid } from "@/test/fixtures/grids";
import { feeder } from "@/test/fixtures/networks";

vi.mock("next/navigation", () => ({
  usePathname: () => "/grid/x",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

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

function topology(version = 3): ApiResult<Topology> {
  return {
    ok: true,
    status: 200,
    data: {
      gridId: FIXTURE_GRID_ID,
      version,
      topologyHash: "ab".repeat(32),
      dataOrigin: "synthetic",
      network: feeder(),
    },
    etag: version,
    location: null,
    headers: new Headers(),
  };
}

function workspace(
  tab: "overview" | "assets" | "settings",
  grid: () => Promise<ApiResult<Grid>> = async () => found(),
  topo: () => Promise<ApiResult<Topology>> = async () => topology(),
) {
  return render(
    <GridWorkspace id={FIXTURE_GRID_ID} tab={tab} loadGrid={grid} loadTopology={topo} />,
  );
}

describe("GridWorkspace", () => {
  it("shows the header, the tabs and the overview, labelled synthetic", async () => {
    workspace("overview");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Fixture feeder" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Synthetic data").length).toBeGreaterThan(0);
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(screen.getByText("Unit-test fixture, not a real network.")).toBeInTheDocument();
    expect(screen.getByTitle("ab".repeat(32))).toHaveTextContent("abababababab…");
    expect(screen.getByText("50 Hz")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Elements by type" })).toHaveTextContent(
      "External grids1",
    );
    // The development-mode notice is shown once, by the application shell (app-shell.test.tsx).
    expect(screen.getByRole("heading", { level: 2, name: "Network" })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "Grid sections" });
    expect(tabs.querySelector('[aria-current="page"]')).toHaveTextContent("Overview");
    expect(screen.getByRole("link", { name: "Assets" })).toHaveAttribute(
      "href",
      `/grid/${FIXTURE_GRID_ID}/assets`,
    );
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      `/grid/${FIXTURE_GRID_ID}/settings`,
    );
  });

  it("opens the Assets and Settings tabs", async () => {
    const { unmount } = workspace("assets");
    expect(await screen.findByRole("heading", { level: 2, name: "Assets" })).toBeInTheDocument();
    unmount();
    workspace("settings");
    expect(
      await screen.findByRole("heading", { level: 2, name: "Name and description" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Delete grid" })).toBeInTheDocument();
  });

  it("makes no request for an id that cannot be a grid", async () => {
    const load = vi.fn<typeof fetchGrid>();
    render(
      <GridWorkspace id="demo-feeder" tab="overview" loadGrid={load} loadTopology={vi.fn()} />,
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "Grid not found" }),
    ).toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });

  it("says when the grid does not exist or is another organisation's", async () => {
    workspace("overview", async () => ({
      ok: false,
      failure: { kind: "not_found", code: "grid_not_found", message: "Grid not found" },
    }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The grid does not exist, or it belongs to another organisation.",
    );
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it.each<[ApiFailure, string]>([
    [{ kind: "unreachable", message: "No response from the API" }, "The API is unreachable"],
    [{ kind: "unexpected", status: 200, message: "bad shape" }, "Unexpected answer from the API"],
  ])("shows its own state when the network fails to load: %o", async (failure, title) => {
    workspace(
      "overview",
      async () => found(),
      async () => ({ ok: false, failure }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(title);
  });

  it("warns when the details and the network are different versions", async () => {
    workspace(
      "overview",
      async () => found(),
      async () => topology(4),
    );
    expect(await screen.findByText("The grid changed while this page loaded")).toBeInTheDocument();
    expect(screen.getByText(/details are version 3; the network is version 4/)).toBeInTheDocument();
  });

  it("omits an empty description", async () => {
    workspace("overview", async () => found({ description: "" }));
    await screen.findByRole("heading", { level: 1, name: "Fixture feeder" });
    expect(screen.queryByText("Unit-test fixture, not a real network.")).not.toBeInTheDocument();
  });
});
