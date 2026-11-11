import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.WEB_PORT ?? 3100);
// "localhost", not 127.0.0.1: the API's CORS allow-list is origin-exact.
const baseURL = `http://localhost:${port}`;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Needs a production build (`pnpm build`) and, for the live-status test, the API.
  webServer: {
    command: "pnpm start",
    url: `${baseURL}/dashboard`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
