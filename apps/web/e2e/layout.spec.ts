import { type Page, expect, test } from "@playwright/test";

/**
 * Layout guard (decision 0015): at each supported width, no page scrolls sideways and no
 * page logs a console error. Tables and the network diagram may scroll inside their own
 * boxes; the page itself may not. Read-only, on the seeded synthetic demonstration grid.
 */

const DEMO = "d0000000-0000-4000-8000-000000000002";
const PAGES = [
  "/dashboard",
  "/grid",
  `/grid/${DEMO}`,
  `/grid/${DEMO}/assets`,
  `/grid/${DEMO}/settings`,
  "/assets",
  "/simulations",
  "/simulations/new",
  "/simulations/scenarios",
  "/monitoring",
];
const WIDTHS = [1440, 1280, 768, 390];

async function sidewaysOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

for (const width of WIDTHS) {
  test(`no page scrolls sideways or logs an error at ${width} px`, async ({ page }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width, height: 900 });
    const problems: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") problems.push(`${page.url()}: ${message.text()}`);
    });
    page.on("pageerror", (error) => problems.push(`${page.url()}: ${error.message}`));
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      expect(await sidewaysOverflow(page), `${path} at ${width} px`).toBeLessThanOrEqual(0);
    }
    expect(problems).toEqual([]);
  });
}

test("below 1024 px the navigation is a drawer that opens, navigates and closes", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dashboard");
  const menu = page.getByRole("button", { name: "Open navigation" });
  await expect(menu).toBeVisible();
  await menu.click();
  const drawer = page.locator("#navigation-drawer");
  await expect(drawer.getByRole("link", { name: "Dashboard" })).toBeFocused();
  await drawer.getByRole("link", { name: "Simulations" }).click();
  await expect(page).toHaveURL(/\/simulations$/);
  await expect(drawer).toHaveCount(0);
});
