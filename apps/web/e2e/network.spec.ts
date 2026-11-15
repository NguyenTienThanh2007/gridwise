import { type Page, expect, test } from "@playwright/test";

/**
 * The network explorer on the seeded synthetic CIGRE MV grid (`make seed-demo`; the CI job
 * seeds it). Read-only: nothing here changes stored data.
 */

const DEMO_GRID = "/grid/d0000000-0000-4000-8000-000000000002";

function collectProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(error.message));
  return problems;
}

const drawn = (page: Page, type: string) => page.locator(`svg [data-element^="${type}:"]`);

test("the CIGRE MV grid is drawn at its stored positions, labelled synthetic", async ({ page }) => {
  const problems = collectProblems(page);
  await page.goto(DEMO_GRID);
  const diagram = page.getByRole("group", { name: "Network diagram" });
  await expect(diagram).toBeVisible();
  await expect(page.getByRole("main").getByText("Synthetic data").first()).toBeVisible();
  await expect(page.getByText(/No live measurements or electrical state/)).toBeVisible();
  await expect(page.getByText("Schematic layout")).toHaveCount(0); // every bus has a position

  await expect(drawn(page, "buses")).toHaveCount(15);
  await expect(drawn(page, "lines")).toHaveCount(15);
  await expect(drawn(page, "transformers")).toHaveCount(2);
  await expect(drawn(page, "switches")).toHaveCount(8);
  await expect(drawn(page, "loads")).toHaveCount(18);
  await expect(drawn(page, "generators")).toHaveCount(9);
  await expect(drawn(page, "external_grids")).toHaveCount(1);
  await expect(page.locator('svg [data-switch-position="open"]')).toHaveCount(3);
  expect(problems).toEqual([]);
});

test("an open switch chosen from the list is inspected and kept in the address", async ({
  page,
}) => {
  await page.goto(DEMO_GRID);
  const list = page.getByRole("region", { name: "Elements" });
  await list.getByRole("button", { name: /S2 switch-1/ }).click();
  await expect(page).toHaveURL(/element=switches%3Aswitch-1/);
  const inspector = page.getByRole("region", { name: "Switch" });
  await expect(inspector.getByText("Model position: open")).toBeVisible();
  await expect(inspector.getByRole("button", { name: /Bus 7/ })).toBeVisible();
  await expect(page.locator('[data-element="switches:switch-1"]')).toHaveAttribute(
    "data-selected",
    "true",
  );

  // The selection survives a reload.
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Switch" }).getByText("Model position: open"),
  ).toBeVisible();
});

test("a line clicked in the diagram is inspected with its buses", async ({ page }) => {
  await page.goto(DEMO_GRID);
  // A real mouse click on the middle of a line that nothing else covers. A straight line's
  // box has no width (SVG boxes leave out the stroke), so the click goes to its centre.
  const line = page.locator('[data-element="lines:line-2-3"]');
  await line.scrollIntoViewIfNeeded();
  const box = await line.boundingBox();
  if (box === null) throw new Error("line-2-3 is not drawn");
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  const inspector = page.getByRole("region", { name: "Line" });
  await expect(inspector.getByText("Line 2-3")).toBeVisible();
  await expect(inspector.getByRole("button", { name: /Bus 2/ })).toBeVisible();
  await inspector.getByRole("button", { name: /Bus 3/ }).click();
  await expect(
    page.getByRole("region", { name: "Bus" }).getByText("Connected at this bus"),
  ).toBeVisible();
});

test("the keyboard alone reaches and selects an element", async ({ page }) => {
  await page.goto(DEMO_GRID);
  await page.getByLabel("Filter by name or key").focus();
  await page.keyboard.type("trafo-0-12");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: /trafo-0-12/ })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("region", { name: "Transformer" }).getByText("Rated power"),
  ).toBeVisible();
});

test("zoom and fit change the visible part of the diagram", async ({ page }) => {
  await page.goto(DEMO_GRID);
  const diagram = page.getByRole("group", { name: "Network diagram" });
  const fitted = await diagram.getAttribute("viewBox");
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(diagram).not.toHaveAttribute("viewBox", fitted ?? "");
  await page.getByRole("button", { name: "Fit" }).click();
  await expect(diagram).toHaveAttribute("viewBox", fitted ?? "");
});
