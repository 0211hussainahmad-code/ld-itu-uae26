import { defineConfig, devices } from "@playwright/test";

// Local runs use the preinstalled Chromium; CI installs browsers itself.
export default defineConfig({
  testDir: "tests/e2e",
  timeout: 30_000,
  retries: 0,
  reporter: process.env.E2E_JSON ? [["list"], ["json", { outputFile: process.env.E2E_JSON }]] : [["list"]],
  // Against a protected preview, Access credentials are added per request to that one origin only,
  // by tests/e2e/fixtures.ts. Never put them in `extraHTTPHeaders`: those go to every origin.
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:4173" },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : { command: "npm run preview", url: "http://localhost:4173", reuseExistingServer: false, timeout: 60_000 },
  projects: [
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } },
    { name: "chromium-mobile", use: { ...devices["Pixel 7"] } },
    // Other engines run where their browser builds can be installed (CI job "browsers"; E2E_ALL_BROWSERS=1).
    ...(process.env.E2E_ALL_BROWSERS ? [
      { name: "firefox-desktop", use: { ...devices["Desktop Firefox"], viewport: { width: 1440, height: 900 } } },
      { name: "webkit-desktop", use: { ...devices["Desktop Safari"], viewport: { width: 1440, height: 900 } } },
      { name: "webkit-mobile", use: { ...devices["iPhone 13"] } },
    ] : []),
  ],
});
