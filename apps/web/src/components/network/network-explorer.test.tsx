import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NetworkExplorer } from "@/components/network/network-explorer";
import type { ApiResult } from "@/lib/http/client";
import type { Network, Topology } from "@/lib/resources/topology";
import { bus, feeder, line, network } from "@/test/fixtures/networks";

// The address bar, as a tiny store: router.replace changes it, useSearchParams reads it.
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
    usePathname: () => "/grid/g",
    useRouter: () => ({ replace: (url: string) => address.set(url.split("?")[1] ?? "") }),
    useSearchParams: () =>
      new URLSearchParams(useSyncExternalStore(address.subscribe, address.get)),
  };
});

const GRID_ID = "0a0a0a0a-0000-4000-8000-0000000000f1";

function topology(net: Network, version = 3): ApiResult<Topology> {
  return {
    ok: true,
    status: 200,
    data: {
      gridId: GRID_ID,
      version,
      topologyHash: "ab".repeat(32),
      dataOrigin: "synthetic",
      network: net,
    },
    etag: version,
    location: null,
    headers: new Headers(),
  };
}

function explore(result: ApiResult<Topology>) {
  if (!result.ok) throw new Error("the explorer is given a loaded topology");
  return render(<NetworkExplorer gridId={GRID_ID} topology={result.data} />);
}

beforeEach(() => address.set(""));

describe("NetworkExplorer", () => {
  it("draws the network labelled synthetic, with no claim of live state", async () => {
    explore(topology(feeder()));
    expect(await screen.findByRole("group", { name: "Network diagram" })).toBeInTheDocument();
    expect(screen.getByText("Synthetic data")).toBeInTheDocument();
    expect(screen.getByText(/No live measurements or electrical state/)).toBeInTheDocument();
    expect(screen.queryByText(/energi[sz]ed/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Schematic layout")).not.toBeInTheDocument();
  });

  it("selects from the list with the keyboard and keeps the selection in the address", async () => {
    explore(topology(feeder()));
    const list = within(await screen.findByRole("region", { name: "Elements" }));
    const button = list.getByRole("button", { name: /Switch s-bc/ });
    expect(button).toHaveTextContent("Model position: open");
    button.focus();
    fireEvent.keyDown(button, { key: "Enter" });
    fireEvent.click(button); // what Enter does on a native button
    expect(address.get()).toBe("element=switches%3As-bc");
    expect(button).toHaveAttribute("aria-pressed", "true");
    const inspector = within(screen.getByRole("region", { name: "Switch" }));
    expect(inspector.getByText("Switch s-bc")).toBeInTheDocument();
    expect(document.querySelector('[data-element="switches:s-bc"]')).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  it("selects from the diagram", async () => {
    explore(topology(feeder()));
    await screen.findByRole("group", { name: "Network diagram" });
    fireEvent.click(document.querySelector('[data-element="transformers:t1"]') as Element);
    expect(
      within(screen.getByRole("region", { name: "Transformer" })).getByText("Transformer t1"),
    ).toBeInTheDocument();
  });

  it("reads a selection from the address and ignores one this network does not have", async () => {
    address.set("element=buses%3Ab");
    const { unmount } = explore(topology(feeder()));
    expect(await screen.findByRole("region", { name: "Bus" })).toBeInTheDocument();
    unmount();
    address.set("element=buses%3Anope");
    explore(topology(feeder()));
    expect(
      await screen.findByText("Select an element in the diagram or in the element list."),
    ).toBeInTheDocument();
  });

  it("filters the list by name or key", async () => {
    explore(topology(feeder()));
    const list = within(await screen.findByRole("region", { name: "Elements" }));
    fireEvent.change(list.getByLabelText("Filter by name or key"), { target: { value: "load" } });
    const names = list.getAllByRole("button").map((b) => b.textContent ?? "");
    expect(names).toHaveLength(2);
    expect(names[0]).toMatch(/^Load load-b/);
    expect(names[1]).toMatch(/^Load load-c/);
    fireEvent.change(list.getByLabelText("Filter by name or key"), { target: { value: "zzz" } });
    expect(list.getByText("No element matches “zzz”.")).toBeInTheDocument();
  });

  it("zooms and fits with buttons", async () => {
    explore(topology(feeder()));
    const diagram = await screen.findByRole("group", { name: "Network diagram" });
    const fitted = diagram.getAttribute("viewBox");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(diagram.getAttribute("viewBox")).not.toBe(fitted);
    fireEvent.click(screen.getByRole("button", { name: "Fit" }));
    expect(diagram.getAttribute("viewBox")).toBe(fitted);
  });

  it("says when the layout is computed because positions are missing", async () => {
    const net = feeder();
    explore(topology({ ...net, buses: net.buses.map((b) => ({ ...b, diagram: null })) }));
    expect(await screen.findByText("Schematic layout")).toBeInTheDocument();
    expect(screen.getByText(/4 of 4 buses have no stored diagram position/)).toBeInTheDocument();
  });

  it("draws nothing for a topology with broken references, and lists them", async () => {
    explore(topology(network({ buses: [bus("a")], lines: [line("l1", "a", "ghost")] })));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This topology cannot be drawn");
    expect(alert).toHaveTextContent("to_bus_key refers to ghost");
    expect(screen.queryByRole("group", { name: "Network diagram" })).not.toBeInTheDocument();
  });

  it("says when there are no buses", async () => {
    explore(topology(network({})));
    expect(await screen.findByText("This grid has no buses to draw")).toBeInTheDocument();
  });

  it("links the inspected element to its edit form in the Assets tab", async () => {
    explore(topology(feeder()));
    const list = within(await screen.findByRole("region", { name: "Elements" }));
    fireEvent.click(list.getByRole("button", { name: /Line l-ab/ }));
    expect(screen.getByRole("link", { name: "Edit in Assets" })).toHaveAttribute(
      "href",
      `/grid/${GRID_ID}/assets?element=lines%3Al-ab`,
    );
  });
});
