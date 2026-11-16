import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";
import { NAV_ITEMS } from "@/lib/navigation";

vi.mock("next/navigation", () => ({ usePathname: () => "/grid/feeder-7" }));

describe("AppShell", () => {
  it("links every primary route and marks the current section", () => {
    render(
      <AppShell>
        <p>content</p>
      </AppShell>,
    );
    const nav = within(screen.getByRole("navigation", { name: "Primary" }));
    for (const item of NAV_ITEMS) {
      expect(nav.getByRole("link", { name: new RegExp(`^${item.label}`) })).toHaveAttribute(
        "href",
        item.href,
      );
    }
    expect(nav.getByRole("link", { name: "Grids" })).toHaveAttribute("aria-current", "page");
    expect(nav.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("groups the sections that are still placeholders as planned, with their phase", () => {
    render(<AppShell>content</AppShell>);
    const nav = within(screen.getByRole("navigation", { name: "Primary" }));
    expect(nav.getByText("Planned")).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Monitoring, planned for P2" })).toHaveAttribute(
      "href",
      "/monitoring",
    );
  });

  it("always states the simulation-only boundary and the development mode, once", () => {
    render(<AppShell>content</AppShell>);
    expect(screen.getByText("Simulation and decision support only")).toBeInTheDocument();
    expect(screen.getAllByText("Development mode.")).toHaveLength(1);
    expect(screen.getByRole("main")).toHaveTextContent("content");
  });

  it("opens the navigation drawer from the menu button and closes it with Escape", () => {
    render(<AppShell>content</AppShell>);
    const button = screen.getByRole("button", { name: "Open navigation" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(
      screen.getByRole("button", { name: "Close navigation", expanded: true }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("navigation", { name: "Primary" })).toHaveLength(2);
    const drawerNav = screen.getAllByRole("navigation", { name: "Primary" })[1] as HTMLElement;
    expect(within(drawerNav).getByRole("link", { name: "Dashboard" })).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getAllByRole("navigation", { name: "Primary" })).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveFocus();
  });
});
