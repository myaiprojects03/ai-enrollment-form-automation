import { defineConfig, devices } from "@playwright/test";

/** The review console against a running engine and web app (see docs/SETUP.md):
 *  CONSOLE_URL (web, default http://localhost:3100), ENGINE_URL (default http://localhost:8000),
 *  OPERATOR_TOKEN (to seed records), CONSOLE_EMAIL and CONSOLE_PASSWORD (a STAFF_ACCOUNTS entry). */
export default defineConfig({
  testDir: "./e2e-console",
  timeout: 90_000,
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: process.env.CONSOLE_URL ?? "http://localhost:3100", trace: "retain-on-failure", ...devices["Desktop Chrome"] },
});
