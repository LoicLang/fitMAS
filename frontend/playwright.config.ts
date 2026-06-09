import { defineConfig } from "@playwright/test";

// E2E for the V0 webapp. Boots the API in V0 mode against a freshly-seeded V0 store
// (today's planned running session + an off-plan running activity) plus the Vite dev
// server (which proxies /api -> the API). Tests drive the real browser UI.
const REPO_ROOT = "..";
const E2E_DB = "/tmp/fitmas_e2e_v0.db";
const E2E_LEGACY_DB = "/tmp/fitmas_e2e_legacy.db";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
  },
  webServer: [
    {
      // Seed a fresh V0 store, then serve the API in V0 mode on the port Vite proxies to.
      command:
        `PYTHONPATH=backend/src .venv/bin/python scripts/e2e_seed_v0.py ${E2E_DB} && ` +
        `FITMAS_APP_SOURCE=v0 FITMAS_V0_DB_PATH=${E2E_DB} FITMAS_DB_PATH=${E2E_LEGACY_DB} ` +
        `.venv/bin/python -m uvicorn --app-dir backend/src fitmas.legacy.api:app --port 8033`,
      url: "http://127.0.0.1:8033/health",
      cwd: REPO_ROOT,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev",
      url: "http://localhost:5173",
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
