import { expect, test } from "@playwright/test";
import { API_URL, type GridCopy, copyDemoGrid, deleteIfPresent } from "./support/grid-copy";

/** Grid name, description and deletion, on a private copy of the synthetic demo grid. */

let grid: GridCopy;

test.beforeEach(async ({ request }, info) => {
  grid = await copyDemoGrid(request, info.title.slice(0, 40));
});

test.afterEach(async ({ request }) => {
  await deleteIfPresent(request, grid.id);
});

test("the name and description are saved, and a taken name is refused", async ({ page }) => {
  await page.goto(`/grid/${grid.id}/settings`);
  await page
    .getByRole("textbox", { name: "Description", exact: true })
    .fill("Edited by an end-to-end test.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved. The grid is now version 2.")).toBeVisible();
  await expect(page.getByText("Edited by an end-to-end test.").first()).toBeVisible();

  await page
    .getByRole("textbox", { name: "Name", exact: true })
    .fill("CIGRE MV benchmark with distributed generation (synthetic)");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Another grid already has this name.")).toBeVisible();
});

test("a grid is deleted only after its exact name is typed", async ({ page, request }) => {
  await page.goto(`/grid/${grid.id}/settings`);
  const button = page.getByRole("button", { name: "Delete grid permanently" });
  await expect(page.getByText(/This cannot be undone/)).toBeVisible();
  await page.getByLabel(/Type the grid's name to confirm/).fill(grid.name.toUpperCase());
  await expect(button).toBeDisabled();
  await page.getByLabel(/Type the grid's name to confirm/).fill(grid.name);
  await button.click();

  await expect(page).toHaveURL(/\/grid\?deleted=1$/);
  await expect(page.getByText("The grid was deleted.")).toBeVisible();
  expect((await request.get(`${API_URL}/api/v1/grids/${grid.id}`)).status()).toBe(404);
});
