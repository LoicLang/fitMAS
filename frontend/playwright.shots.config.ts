import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Screenshot generation for the README — reuses the seeded API + Vite web servers
// from the base e2e config, but only runs e2e/capture-shots.ts (not the test gate).
export default defineConfig({
  ...base,
  testMatch: ["**/capture-shots.ts"],
});
