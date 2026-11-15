import { type Page, expect, test } from "@playwright/test";
import {
  API_URL,
  type GridCopy,
  copyDemoGrid,
  deleteIfPresent,
  gridVersion,
  tabTo,
} from "./support/grid-copy";

/**
 * Asset management on a private copy of the synthetic CIGRE MV grid. Changes here edit the
 * stored simulation model only; nothing is sent to any equipment.
 */

let grid: GridCopy;

test.beforeEach(async ({ request }, info) => {
  grid = await copyDemoGrid(request, info.title.slice(0, 40));
});

test.afterEach(async ({ request }) => {
  await deleteIfPresent(request, grid.id);
});

const rowsShown = (page: Page) => page.locator("tbody tr[data-asset]");

test("assets are filtered by type, state and text, kept in the address", async ({ page }) => {
  await page.goto(`/grid/${grid.id}/assets`);
  await expect(page.getByText("68 of 68 elements")).toBeVisible();
  await page.getByLabel("Type").selectOption("switches");
  await page.getByLabel("State").selectOption("open");
  await expect(rowsShown(page)).toHaveCount(3);
  await expect(page).toHaveURL(/type=switches&state=open/);
  await page.getByLabel("Search name or key").fill("switch-1");
  await expect(rowsShown(page)).toHaveCount(1);
  await expect(page.getByText("Synthetic model data. Not measurements.")).toBeVisible();
});

test("a line taken out of service after review is dashed in the diagram", async ({ page }) => {
  await page.goto(`/grid/${grid.id}/assets?type=lines`);
  await page.getByRole("button", { name: "Line 3-8" }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("radio", { name: "Out of service" }).check();
  await page.getByRole("button", { name: "Review change" }).click();
  await expect(page.getByText(/Nothing is sent to any equipment/)).toBeVisible();
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Saved. The grid is now version 2.")).toBeVisible();
  await expect(page.locator('[data-asset="lines:line-3-8"]')).toContainText("Out of service");

  await page
    .getByRole("navigation", { name: "Grid sections" })
    .getByRole("link", { name: "Overview" })
    .click();
  await expect(page.locator('[data-element="lines:line-3-8"] title')).toHaveText(
    "Line 3-8 (line), out of service",
  );
  await expect(page.getByText("Version 2")).toBeVisible();
});

test("a switch's model position is set after review", async ({ page }) => {
  await page.goto(`/grid/${grid.id}/assets?type=switches`);
  await page.getByRole("button", { name: "S2" }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("group", { name: "Model position" })).toContainText(
    "not a command to any equipment",
  );
  await page.getByRole("radio", { name: "Closed" }).check();
  await page.getByRole("button", { name: "Review change" }).click();
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByText("Saved. The grid is now version 2.")).toBeVisible();
  await expect(page.locator('[data-asset="switches:switch-1"]')).toContainText(
    "Model position: closed",
  );
});

test("a change saved elsewhere first is never overwritten", async ({ page, request }) => {
  await page.goto(`/grid/${grid.id}/assets?type=loads`);
  await page.getByRole("button", { name: "Load R1", exact: true }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByLabel("Name", { exact: true }).fill("Load R1 (renamed in the UI)");

  // Someone else changes the grid while the form is open.
  const other = await request.patch(`${API_URL}/api/v1/grids/${grid.id}/assets/lines/line-1-2`, {
    data: { name: "Line 1-2 (renamed elsewhere)" },
    headers: { "If-Match": '"1"' },
  });
  expect(other.status()).toBe(200);

  await page.getByRole("button", { name: "Save" }).click();
  const alert = page.getByRole("main").getByRole("alert");
  await expect(alert).toContainText("It is now version 2");
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue("Load R1 (renamed in the UI)");
  expect(await gridVersion(request, grid.id)).toBe(2);

  await page.getByRole("button", { name: "Reload and review" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved. The grid is now version 3.")).toBeVisible();
  const line = await request.get(`${API_URL}/api/v1/grids/${grid.id}/assets/lines/line-1-2`);
  expect(((await line.json()) as { asset: { name: string } }).asset.name).toBe(
    "Line 1-2 (renamed elsewhere)",
  );
});

test("a change that would leave the grid invalid is refused, and nothing is stored", async ({
  page,
  request,
}) => {
  await page.goto(`/grid/${grid.id}/assets?type=external_grids`);
  await page.getByRole("button", { name: "External grid 0" }).click();
  await page.getByRole("button", { name: "Edit" }).click();
  await page.getByRole("radio", { name: "Out of service" }).check();
  await page.getByRole("button", { name: "Review change" }).click();
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "the grid would not be valid",
  );
  expect(await gridVersion(request, grid.id)).toBe(1);
});

test("the keyboard alone filters, selects and renames an asset", async ({ page }) => {
  await page.goto(`/grid/${grid.id}/assets`);
  await page.getByLabel("Search name or key").focus();
  await page.keyboard.type("line-1-2");
  const row = page.getByRole("button", { name: "Line 1-2" });
  await tabTo(page, row);
  await page.keyboard.press("Enter");
  const edit = page.getByRole("button", { name: "Edit" });
  await tabTo(page, edit);
  await page.keyboard.press("Enter");
  const name = page.getByLabel("Name", { exact: true });
  await tabTo(page, name);
  await page.keyboard.press("End");
  await page.keyboard.type(" (keyboard)");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Saved. The grid is now version 2.")).toBeVisible();
});
