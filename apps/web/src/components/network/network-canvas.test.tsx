import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LABEL_LIMIT, NetworkCanvas } from "@/components/network/network-canvas";
import { layoutNetwork } from "@/lib/network/layout";
import { fitView } from "@/lib/network/view";
import type { Network } from "@/lib/resources/topology";
import { bus, feeder, load, network } from "@/test/fixtures/networks";

function draw(net: Network, onSelect = vi.fn(), selected = null) {
  const layout = layoutNetwork(net);
  const result = render(
    <NetworkCanvas
      network={net}
      layout={layout}
      view={fitView(layout.bounds)}
      selected={selected}
      onSelect={onSelect}
      onViewChange={vi.fn()}
    />,
  );
  const element = (ref: string) => result.container.querySelector(`[data-element="${ref}"]`);
  return { ...result, element, onSelect };
}

describe("NetworkCanvas", () => {
  it("draws one shape per element", () => {
    const { container } = draw(feeder());
    const refs = [...container.querySelectorAll("[data-element]")].map((node) =>
      node.getAttribute("data-element"),
    );
    expect(refs.sort()).toEqual(
      [
        "buses:a",
        "buses:b",
        "buses:c",
        "buses:hv",
        "lines:l-ab",
        "lines:l-bc",
        "lines:l-ca",
        "transformers:t1",
        "switches:s-ab",
        "switches:s-bc",
        "loads:load-b",
        "loads:load-c",
        "generators:pv-b",
        "external_grids:upstream",
      ].sort(),
    );
  });

  it("tells open and closed switches apart by shape and by name", () => {
    const { element } = draw(feeder());
    const open = element("switches:s-bc");
    const closed = element("switches:s-ab");
    expect(
      open?.querySelector("[data-switch-position]")?.getAttribute("data-switch-position"),
    ).toBe("open");
    expect(
      closed?.querySelector("[data-switch-position]")?.getAttribute("data-switch-position"),
    ).toBe("closed");
    expect(open?.querySelector("title")?.textContent).toBe(
      "Switch s-bc (switch), model position open",
    );
    expect(closed?.querySelector("rect")?.getAttribute("class")).toContain("fill-ink");
  });

  it("dashes out-of-service elements and names their state", () => {
    const { element } = draw(feeder());
    const ring = element("lines:l-ca");
    expect(ring?.querySelector("title")?.textContent).toBe("Line l-ca (line), out of service");
    expect(ring?.querySelectorAll("path")[1]?.getAttribute("stroke-dasharray")).toBe("5 4");
    expect(
      element("lines:l-ab")?.querySelectorAll("path")[1]?.getAttribute("stroke-dasharray"),
    ).toBeNull();
    expect(element("buses:c")?.querySelector("title")?.textContent).toContain("out of service");
  });

  it("selects what is clicked", () => {
    const { element, onSelect } = draw(feeder());
    fireEvent.click(element("lines:l-ab") as Element);
    expect(onSelect).toHaveBeenCalledWith({ type: "lines", key: "l-ab" });
  });

  it("counts attached elements beyond the limit", () => {
    const net = network({
      buses: [bus("a", { x: 0, y: 0 })],
      loads: Array.from({ length: 6 }, (_, i) => load(`load-${i}`, "a")),
    });
    const { container } = draw(net);
    expect(container.querySelector('[data-overflow="loads"] text')?.textContent).toBe("+2");
  });

  it("labels buses only below the label limit", () => {
    expect(draw(feeder()).container.querySelectorAll("text").length).toBe(4);
    const many = network({
      buses: Array.from({ length: LABEL_LIMIT + 1 }, (_, i) => bus(`b${i}`, { x: i, y: 0 })),
    });
    expect(draw(many).container.querySelectorAll("text").length).toBe(0);
  });

  it("is a labelled group that points to the keyboard path", () => {
    const { getByRole } = draw(feeder());
    const diagram = getByRole("group", { name: "Network diagram" });
    expect(diagram).toHaveAccessibleDescription(/use the element list/);
  });
});
