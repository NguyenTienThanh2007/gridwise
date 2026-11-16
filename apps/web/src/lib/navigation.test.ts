import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NAV_ITEMS, isActive } from "@/lib/navigation";

const APP_DIR = path.join(import.meta.dirname, "../app");

describe("navigation", () => {
  it("covers the primary routes of the product brief", () => {
    // Working sections first; the planned placeholders after them (decision 0015).
    expect(NAV_ITEMS.map((item) => item.href)).toEqual([
      "/dashboard",
      "/grid",
      "/simulations",
      "/assets",
      "/monitoring",
      "/analytics",
      "/forecasting",
      "/alerts",
      "/settings",
    ]);
    expect(NAV_ITEMS.filter((item) => item.group === "planned").map((item) => item.phase)).toEqual([
      "P2",
      "P3",
      "P4",
      "P2",
      "P6",
    ]);
  });

  it.each([...NAV_ITEMS.map((item) => item.href), "/grid/[id]"])("%s has a page", (href) => {
    expect(existsSync(path.join(APP_DIR, href, "page.tsx"))).toBe(true);
  });

  it("marks a section active for itself and its children only", () => {
    expect(isActive("/grid", "/grid")).toBe(true);
    expect(isActive("/grid/abc", "/grid")).toBe(true);
    expect(isActive("/gridlock", "/grid")).toBe(false);
    expect(isActive("/dashboard", "/grid")).toBe(false);
  });
});
