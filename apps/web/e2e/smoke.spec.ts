import { expect, test } from "@playwright/test";

const SECTIONS = [
  "Grid",
  "Monitoring",
  "Analytics",
  "Forecasting",
  "Simulations",
  "Alerts",
  "Assets",
  "Settings",
];

test("home redirects to the dashboard, which shows live API status", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(message.text());
  });
  page.on("pageerror", (error) => problems.push(error.message));

  await page.goto("/");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible();

  // Real round trip: browser -> API -> PostgreSQL.
  await expect(page.getByRole("status")).toHaveText("Ready");
  await expect(page.getByText("Connected")).toBeVisible();
  await expect(page.getByText("does not issue switching commands")).toBeVisible();

  // The Content-Security-Policy must not block anything the application needs.
  expect(problems).toEqual([]);
});

test("every page is served with security headers", async ({ page }) => {
  for (const path of ["/dashboard", "/grid/demo-feeder", "/does-not-exist"]) {
    const response = await page.goto(path);
    const headers = response?.headers() ?? {};
    expect(headers["x-content-type-options"], path).toBe("nosniff");
    expect(headers["referrer-policy"], path).toBe("strict-origin-when-cross-origin");
    expect(headers["x-frame-options"], path).toBe("DENY");
    const policy = headers["content-security-policy"] ?? "";
    expect(policy, path).toContain("default-src 'self'");
    expect(policy, path).toContain("frame-ancestors 'none'");
    expect(policy, path).toContain("object-src 'none'");
    expect(policy, path).not.toContain("unsafe-eval");
    expect(headers["x-powered-by"], path).toBeUndefined();
  }
});

test("the policy blocks a script from another origin", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy")) violations.push(message.text());
  });
  await page.goto("/dashboard");
  await page.evaluate(() => {
    const script = document.createElement("script");
    script.src = "https://evil.example.test/x.js";
    document.head.appendChild(script);
  });
  await expect.poll(() => violations.length).toBeGreaterThan(0);
});

test("every section is reachable and honest about being unimplemented", async ({ page }) => {
  await page.goto("/dashboard");
  for (const name of SECTIONS) {
    await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name }).click();
    await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
    await expect(page.getByText("Not implemented yet")).toBeVisible();
  }
});

test("grid detail route renders without pretending the grid exists", async ({ page }) => {
  await page.goto("/grid/demo-feeder");
  await expect(page.getByText('Requested grid "demo-feeder"')).toBeVisible();
});

test("dashboard reports an unreachable API instead of failing silently", async ({ page }) => {
  await page.route("**/health/ready", (route) => route.abort());
  await page.goto("/dashboard");
  await expect(page.getByRole("status")).toHaveText("API unreachable");
});

test("an API that accepts but never answers times out and Refresh works again", async ({
  page,
}) => {
  test.setTimeout(40_000);
  // Leave the request pending for ever: no fulfil, no abort.
  await page.route("**/health/ready", () => undefined);
  await page.goto("/dashboard");

  await expect(page.getByRole("status")).toHaveText("Checking…");
  await expect(page.getByRole("button", { name: "Refresh" })).toBeDisabled();

  await expect(page.getByRole("status")).toHaveText("API unreachable", { timeout: 15_000 });
  await expect(page.getByText("No response within 8 seconds")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh" })).toBeEnabled();

  // Once the API answers again, Refresh recovers without a page reload.
  await page.unroute("**/health/ready");
  await page.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("status")).toHaveText("Ready");
});
