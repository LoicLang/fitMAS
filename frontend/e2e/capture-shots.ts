import { test } from "@playwright/test";

// Generates the README screenshot from SEEDED/synthetic data (no real activity,
// no real GPS). Run with: npm run shots
test("README — rich session detail", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1120 });

  // Link the seeded activity to the day's session so the detail shows the realized run.
  await page.goto("/calendar");
  await page.getByRole("button", { name: /Lier à/ }).click();
  await page.waitForLoadState("networkidle");

  await page.goto("/workout/1");
  await page.getByText("Allure", { exact: true }).waitFor();
  await page.getByTestId("route-map").waitFor({ state: "visible" });
  await page.waitForTimeout(1500); // let the reveal animations settle

  await page.screenshot({ path: "../docs/assets/webapp-session-detail.png" });
});
