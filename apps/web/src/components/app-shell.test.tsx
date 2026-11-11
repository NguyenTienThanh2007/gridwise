import { render, screen, within } from "@testing-library/react";
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
      expect(nav.getByRole("link", { name: item.label })).toHaveAttribute("href", item.href);
    }
    expect(nav.getByRole("link", { name: "Grid" })).toHaveAttribute("aria-current", "page");
    expect(nav.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("always states the simulation-only boundary", () => {
    render(<AppShell>content</AppShell>);
    expect(screen.getByText("Simulation and decision support only")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("content");
  });
});
