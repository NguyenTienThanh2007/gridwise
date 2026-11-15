import { type Page, expect, test } from "@playwright/test";

/**
 * Grid list and grid page against the real API and database. Needs the synthetic
 * demonstration grid (`make seed-demo`; the CI job seeds it). Read-only: nothing here
 * changes stored data.
 */

const DEMO_GRID_ID = "d0000000-0000-4000-8000-000000000002";
const DEMO_GRID_NAME = "CIGRE MV benchmark with distributed generation (synthetic)";
// The same API the build talks to (NEXT_PUBLIC_API_URL is baked in at build time).
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8020";

function collectProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(error.message));
  return problems;
}

test("the grid list shows the demonstration grid, labelled synthetic", async ({ page }) => {
  const problems = collectProblems(page);
  await page.goto("/grid");
  await expect(page.getByRole("heading", { level: 1, name: "Grids" })).toBeVisible();
  await expect(page.getByText("Development mode.")).toBeVisible();

  const table = page.getByRole("table", { name: "Stored grids" });
  const row = table.getByRole("row").filter({ hasText: DEMO_GRID_NAME });
  await expect(row).toContainText("Synthetic data");
  await expect(row.getByRole("cell").nth(3)).toHaveText("15"); // buses

  await row.getByRole("link", { name: DEMO_GRID_NAME }).click();
  await expect(page).toHaveURL(new RegExp(`/grid/${DEMO_GRID_ID}$`));
  await expect(page.getByRole("heading", { level: 1, name: DEMO_GRID_NAME })).toBeVisible();
  expect(problems).toEqual([]);
});

test("the grid page shows the stored model's metadata", async ({ page, request }) => {
  const problems = collectProblems(page);
  const api = await request.get(`${API_URL}/api/v1/grids/${DEMO_GRID_ID}`);
  expect(api.ok()).toBe(true);
  const grid = (await api.json()) as {
    version: number;
    topology_hash: string;
    element_counts: Record<string, number>;
  };

  await page.goto(`/grid/${DEMO_GRID_ID}`);
  await expect(page.getByText("Synthetic data").first()).toBeVisible();
  await expect(page.getByText("Not a real network; contains no measured data.")).toBeVisible();
  await expect(page.getByTitle(grid.topology_hash)).toHaveText(
    `${grid.topology_hash.slice(0, 12)}…`,
  );
  const elements = page.getByRole("table", { name: "Elements by type" });
  await expect(elements.getByRole("row", { name: /Buses/ })).toContainText(
    String(grid.element_counts.buses),
  );
  await expect(elements.getByRole("row", { name: /Switches/ })).toContainText(
    String(grid.element_counts.switches),
  );
  expect(problems).toEqual([]);
});

test("a grid that does not exist is not found", async ({ page }) => {
  await page.goto("/grid/00000000-0000-4000-8000-000000000000");
  await expect(page.getByRole("heading", { level: 1, name: "Grid not found" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "belongs to another organisation",
  );
});

test("an unreachable API is reported, and the list recovers on retry", async ({ page }) => {
  await page.route("**/api/v1/grids?*", (route) => route.abort());
  await page.goto("/grid");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("The API is unreachable");
  await page.unroute("**/api/v1/grids?*");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("table", { name: "Stored grids" })).toBeVisible();
});

test("an API without the grid routes is reported as not available here", async ({ page }) => {
  await page.route("**/api/v1/grids?*", (route) =>
    route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "not_found", message: "Not Found", request_id: null },
      }),
    }),
  );
  await page.goto("/grid");
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "Not available in this environment",
  );
});
