import { existsSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { NAV_ITEMS, isActive } from "@/lib/navigation";

const APP_DIR = path.join(import.meta.dirname, "../app");

describe("navigation", () => {
  it("covers the primary routes of the product brief", () => {
    expect(NAV_ITEMS.map((item) => item.href)).toEqual([
      "/dashboard",
      "/grid",
      "/monitoring",
      "/analytics",
      "/forecasting",
      "/simulations",
      "/alerts",
      "/assets",
      "/settings",
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
