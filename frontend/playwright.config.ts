import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${port}`, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /layout\.spec\.ts/ },
  ],
  webServer: {
    command: `npx next start -p ${port}`,
    url: `http://localhost:${port}/portals/harbour/join`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    env: { PORTAL_API_KEY: "e2e-portal-key" },
  },
});
