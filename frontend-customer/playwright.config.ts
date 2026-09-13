import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests, against the real backend.
 *
 * Nothing is mocked. The unit tests already pin the pure logic; the point of
 * these is the wiring between the parts — a button that renders but never calls
 * anything passes a unit test and fails a customer.
 *
 * Both servers must already be running:
 *   backend    cd backend && ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
 *   frontend   cd frontend-customer && npm run dev
 *
 * They are NOT started here on purpose. The backend needs its own venv, its
 * .env and a reachable Supabase, and a `webServer` block that half-starts it
 * produces a confusing timeout instead of a clear "start the backend".
 */
export default defineConfig({
  testDir: "./e2e",
  // The concierge waits on a local Ollama, which is slow and variable.
  timeout: 180_000,
  expect: { timeout: 20_000 },
  // Serial: these share one database, and a parallel run would have two specs
  // placing orders against the same cart state.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 20_000,
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    // The mobile layout is a different layout, not a narrower one: its own
    // bottom nav, its own branch-picker row, its own sticky order bar.
    //
    // Pixel 5 rather than iPhone, because the iPhone profiles run on WebKit and
    // that is a second browser download. Chromium on a phone viewport with
    // touch still exercises everything this suite is about. For real Safari
    // coverage: `npx playwright install webkit`, then swap in iPhone 13.
    { name: "mobile", use: { ...devices["Pixel 5"] } },
  ],
});
