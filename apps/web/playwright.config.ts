import { defineConfig, devices } from "@playwright/test";

const PORT = 3100;
const screenshots = process.env.SCREENSHOTS === "1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "off",
  },
  // Build once, then serve the production build with the built-in mock API.
  webServer: {
    command: `npm run build && npx next start -H 127.0.0.1 -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 240_000,
    env: { NEXT_PUBLIC_MOCK: "true" },
  },
  projects: [
    { name: "smoke", testMatch: /smoke\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
    ...(screenshots ? [{ name: "screenshots", testMatch: /screenshots\.spec\.ts/, use: { ...devices["Desktop Chrome"] } }] : []),
  ],
});
