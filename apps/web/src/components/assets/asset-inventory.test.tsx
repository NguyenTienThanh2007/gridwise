import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AssetInventory } from "@/components/assets/asset-inventory";
import type { updateAsset } from "@/lib/resources/assets";
import type { Topology } from "@/lib/resources/topology";
import { feeder } from "@/test/fixtures/networks";

const address = vi.hoisted(() => {
  let search = "";
  const listeners = new Set<() => void>();
  return {
    get: () => search,
    set: (value: string) => {
      search = value;
      listeners.forEach((listener) => listener());
    },
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

vi.mock("next/navigation", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    usePathname: () => "/grid/g/assets",
    useRouter: () => ({
      replace: (url: string) => {
        const query = url.split("?")[1] ?? "";
        window.history.replaceState(
          null,
          "",
          query === "" ? window.location.pathname : `?${query}`,
        );
        address.set(query);
      },
    }),
    useSearchParams: () =>
      new URLSearchParams(useSyncExternalStore(address.subscribe, address.get)),
  };
});

const GRID = "0a0a0a0a-0000-4000-8000-0000000000f1";
const topology: Topology = {
  gridId: GRID,
  version: 3,
  topologyHash: "ab".repeat(32),
  dataOrigin: "synthetic",
  network: feeder(),
};

function inventory(update?: typeof updateAsset, onSaved = vi.fn()) {
  render(<AssetInventory gridId={GRID} topology={topology} onSaved={onSaved} update={update} />);
  return onSaved;
}

const names = () =>
  [...document.querySelectorAll("tbody tr")].map((row) => row.getAttribute("data-asset"));

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  address.set("");
});

describe("AssetInventory", () => {
  it("keeps every change when filters change faster than the address", () => {
    inventory();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "lines" } });
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "in_service" } });
    fireEvent.change(screen.getByLabelText("Search name or key"), { target: { value: "a" } });
    fireEvent.change(screen.getByLabelText("Search name or key"), { target: { value: "ab" } });
    expect(screen.getByLabelText("Search name or key")).toHaveValue("ab");
    expect(names()).toEqual(["lines:l-ab"]);
    expect(address.get()).toBe("type=lines&state=in_service&q=ab");
  });

  it("lists every element, labelled synthetic", () => {
    inventory();
    expect(names()).toHaveLength(14);
    expect(screen.getByText("14 of 14 elements")).toBeInTheDocument();
    expect(screen.getByText("Synthetic model data. Not measurements.")).toBeInTheDocument();
  });

  it("filters by type, state and text, and keeps the filters in the address", () => {
    inventory();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "lines" } });
    expect(names()).toEqual(["lines:l-ab", "lines:l-bc", "lines:l-ca"]);
    expect(screen.getByRole("columnheader", { name: "Length" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "out_of_service" } });
    expect(names()).toEqual(["lines:l-ca"]);
    expect(address.get()).toBe("type=lines&state=out_of_service");
    fireEvent.change(screen.getByLabelText("Search name or key"), { target: { value: "zzz" } });
    expect(screen.getByText("No element matches these filters")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(address.get()).toBe("");
  });

  it("offers model positions, not service states, for switches", () => {
    inventory();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "switches" } });
    const options = within(screen.getByLabelText("State"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual([
      "Any state",
      "Switch model position open",
      "Switch model position closed",
    ]);
  });

  it("opens the details and the edit form of the chosen row, and reloads after a save", async () => {
    const update = vi.fn<typeof updateAsset>(async () => ({
      ok: true,
      status: 200,
      data: {
        gridId: GRID,
        gridVersion: 4,
        topologyHash: "x",
        type: "loads",
        asset: feeder().loads[0] as Topology["network"]["loads"][number],
      },
      etag: 4,
      location: null,
      headers: new Headers(),
    }));
    const onSaved = inventory(update);
    fireEvent.click(screen.getByRole("button", { name: "Load load-b" }));
    expect(address.get()).toBe("element=loads%3Aload-b");
    expect(screen.getByRole("button", { name: "Load load-b" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Load B renamed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved. The grid is now version 4.")).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalled();
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });
});
