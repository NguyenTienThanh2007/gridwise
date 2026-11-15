import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ElementInspector } from "@/components/network/element-inspector";
import type { ElementRef } from "@/lib/network/selection";
import { feeder } from "@/test/fixtures/networks";

function inspect(selected: ElementRef | null) {
  const onSelect = vi.fn();
  render(<ElementInspector network={feeder()} selected={selected} onSelect={onSelect} />);
  return onSelect;
}

const row = (label: string) => screen.getByText(label).nextElementSibling;

describe("ElementInspector", () => {
  it("invites a selection when there is none", () => {
    inspect(null);
    expect(
      screen.getByText("Select an element in the diagram or in the element list."),
    ).toBeInTheDocument();
  });

  it("shows a line's stored fields with units, and selects its buses", () => {
    const onSelect = inspect({ type: "lines", key: "l-ab" });
    expect(screen.getByText("Line")).toBeInTheDocument();
    expect(row("Length")).toHaveTextContent("1 km");
    expect(row("Resistance")).toHaveTextContent("0.5 Ω/km");
    expect(row("Thermal limit")).toHaveTextContent("0.3 kA");
    expect(row("Service state")).toHaveTextContent("In service");
    fireEvent.click(screen.getByRole("button", { name: /Bus b/ }));
    expect(onSelect).toHaveBeenCalledWith({ type: "buses", key: "b" });
    expect(screen.getByText("Stored model values. Not measurements.")).toBeInTheDocument();
  });

  it("states a switch's model position and where it sits", () => {
    inspect({ type: "switches", key: "s-bc" });
    expect(screen.getByText("Model position: open")).toBeInTheDocument();
    expect(row("Model position")).toHaveTextContent("Open");
    expect(row("Kind")).toHaveTextContent("Load-break switch");
    expect(row("At bus")).toHaveTextContent("Bus c");
    expect(row("On line")).toHaveTextContent("Line l-bc");
  });

  it("shows values the model does not set as missing, never as zero", () => {
    inspect({ type: "generators", key: "pv-b" });
    expect(row("Voltage set-point")).toHaveTextContent("not set");
    expect(row("Voltage set-point")).not.toHaveTextContent("0");
    expect(row("Reactive power")).toHaveTextContent("0 Mvar");
  });

  it("lists what connects at a bus, and says when it is out of service", () => {
    const onSelect = inspect({ type: "buses", key: "c" });
    expect(row("Service state")).toHaveTextContent("Out of service");
    expect(screen.getAllByText("Out of service")).toHaveLength(2); // the state line and the row
    expect(screen.getByText("Connected at this bus (4)")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Load load-c/ }));
    expect(onSelect).toHaveBeenCalledWith({ type: "loads", key: "load-c" });
  });
});
