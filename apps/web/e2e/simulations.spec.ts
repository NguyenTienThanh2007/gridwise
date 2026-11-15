import { type Page, expect, test } from "@playwright/test";
import { type GridCopy, copyDemoGrid, deleteIfPresent, tabTo } from "./support/grid-copy";

/**
 * The simulation workspace against the real API and worker (the CI job starts the worker
 * profile). Each test simulates its own copy of the synthetic demonstration grid.
 */

let grid: GridCopy;
const unique = () => `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;

test.beforeEach(async ({ request }, info) => {
  grid = await copyDemoGrid(request, info.title.slice(0, 40));
});

test.afterEach(async ({ request }) => {
  await deleteIfPresent(request, grid.id);
});

async function createScenario(page: Page, name: string, factor: string): Promise<void> {
  await page.goto("/simulations/scenarios");
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Factor").fill(factor);
  await page.getByRole("button", { name: "Create scenario" }).click();
  await expect(page.getByRole("heading", { level: 3, name })).toBeVisible();
}

test("a simulation is queued from the grid page and followed until it converges", async ({
  page,
}) => {
  await page.goto(`/grid/${grid.id}`);
  await page.getByRole("link", { name: "Simulate this grid" }).click();
  await expect(page).toHaveURL(new RegExp(`/simulations/new\\?grid=${grid.id}$`));
  await expect(page.getByLabel("Grid")).toHaveValue(grid.id);
  await expect(page.getByText(/Simulates version 1 exactly/)).toBeVisible();
  await page.getByRole("button", { name: "Queue simulation" }).click();

  await expect(page).toHaveURL(/\/simulations\/[0-9a-f-]{36}$/);
  // The page follows the job by itself; nobody reloads it.
  await expect(page.getByText("Completed, converged").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("pandapower", { exact: false })).toBeVisible();
  await expect(page.getByRole("table", { name: "Attempts" })).toContainText("Completed");
  await expect(page.getByRole("link", { name: grid.name })).toBeVisible();

  await page.goto(`/simulations?grid=${grid.id}`);
  const table = page.getByRole("table", { name: "Simulation jobs, newest first" });
  await expect(table.getByRole("row")).toHaveCount(2); // header and the one job
  await expect(table).toContainText("Completed, converged");
  await expect(table).toContainText("Normal operation");
});

test("a scenario is created, used, and a run that does not converge shows no values", async ({
  page,
}) => {
  const name = `E2E load x100 ${unique()}`;
  await createScenario(page, name, "100");
  await page.getByRole("link", { name: "Simulate with this scenario" }).first().click();
  // The link for the newest scenario may not be first; choose it explicitly.
  await page.goto(`/simulations/new?grid=${grid.id}`);
  await page.getByLabel("Scenario").selectOption({ label: name });
  await expect(page.getByText("Scale loads (all) by 100")).toBeVisible();
  await page.getByRole("button", { name: "Queue simulation" }).click();
  await expect(page.getByText("Completed, did not converge").first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByText("This run did not converge: there are no values, and none will be shown."),
  ).toBeVisible();

  await page.goto("/simulations/scenarios");
  await page.getByRole("button", { name: `Delete scenario ${name}` }).click();
  await page.getByRole("button", { name: "Confirm delete" }).click();
  await expect(page.getByRole("heading", { level: 3, name })).toHaveCount(0);
});

test("a scenario with an impossible factor is refused before anything is sent", async ({
  page,
}) => {
  await page.goto("/simulations/scenarios");
  await page.getByLabel("Name", { exact: true }).fill(`E2E bad ${unique()}`);
  await page.getByLabel("Factor").fill("500");
  let posted = false;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/v1/scenarios")) posted = true;
  });
  await page.getByRole("button", { name: "Create scenario" }).click();
  await expect(page.getByText("Use a number above 0 and at most 100.")).toBeVisible();
  expect(posted).toBe(false);
});

test("the keyboard alone queues a simulation", async ({ page }) => {
  await page.goto(`/simulations/new?grid=${grid.id}`);
  const button = page.getByRole("button", { name: "Queue simulation" });
  await expect(button).toBeEnabled();
  await tabTo(page, button);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/simulations\/[0-9a-f-]{36}$/);
});

test("only a queued job offers cancel, and a refused cancel is explained (API mocked)", async ({
  page,
}) => {
  // A real worker claims a job within a second, so the queued state is produced here by
  // rewriting the real job's response; the cancel answer is the API's documented 409.
  await page.goto(`/simulations/new?grid=${grid.id}`);
  await page.getByRole("button", { name: "Queue simulation" }).click();
  await expect(page).toHaveURL(/\/simulations\/[0-9a-f-]{36}$/);
  const jobUrl = page.url();
  await page.route("**/api/v1/simulations/*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    Object.assign(body, {
      status: "queued",
      outcome: null,
      attempt: 0,
      started_at: null,
      finished_at: null,
      attempts: [],
    });
    await route.fulfill({ response, json: body });
  });
  await page.route("**/cancel", (route) =>
    route.fulfill({
      status: 409,
      json: {
        error: {
          code: "job_not_cancellable",
          message: "Only a queued job can be cancelled",
          request_id: null,
          details: [{ location: ["status"], message: "The job is running", type: "running" }],
        },
      },
    }),
  );
  await page.goto(jobUrl);
  await page.getByRole("button", { name: "Cancel job" }).click();
  await page.getByRole("button", { name: "Confirm cancel" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "The job is already running",
  );
  // The page keeps following the (mocked) queued job; stop the mocks before the test ends.
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
