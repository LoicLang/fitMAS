import { test, expect } from "@playwright/test";

// The seed (scripts/e2e_seed_v0.py) puts, on TODAY: a planned running session
// "Footing du jour" and an off-plan running activity "Sortie e2e". The calendar
// selects today by default, so the day panel shows both.
test("link an off-plan activity to a session, then unlink", async ({ page }) => {
  await page.goto("/calendar");

  // The day panel shows the off-plan activity and the planned session.
  const offplanEntry = page.locator("[data-calendar-entry]", { hasText: "Sortie e2e" });
  const sessionEntry = page.locator("[data-calendar-entry]", { hasText: "Footing du jour" });
  await expect(offplanEntry).toBeVisible();
  await expect(sessionEntry).toContainText("prévu");

  // Link the off-plan activity to the planned session.
  const linkButton = page.getByRole("button", { name: /Lier à/ });
  await expect(linkButton).toBeVisible();
  await linkButton.click();

  // The session is now "fait" (done) and the off-plan activity is gone (merged in).
  await expect(sessionEntry).toContainText("fait");
  await expect(offplanEntry).toHaveCount(0);

  // Undo: unlink.
  const unlinkButton = page.getByRole("button", { name: /Délier/ });
  await expect(unlinkButton).toBeVisible();
  await unlinkButton.click();

  // The session is back to "prévu" and the off-plan activity reappears.
  await expect(sessionEntry).toContainText("prévu");
  await expect(page.locator("[data-calendar-entry]", { hasText: "Sortie e2e" })).toBeVisible();
});

test("a linked session detail shows rich Strava metrics + the route map", async ({ page }) => {
  await page.goto("/calendar");

  // Link the off-plan running activity to the day's planned session.
  await page.getByRole("button", { name: /Lier à/ }).click();
  await expect(page.locator("[data-calendar-entry]", { hasText: "Footing du jour" })).toContainText("fait");

  // Open the session detail (session id 1 from the seed).
  await page.goto("/workout/1");

  // The realized activity's rich metrics are shown (not the empty "—" planned view).
  await expect(page.getByText("Allure", { exact: true })).toBeVisible();
  await expect(page.getByText("FC moy", { exact: true })).toBeVisible();
  await expect(page.getByText("Calories", { exact: true })).toBeVisible();
  await expect(page.getByText(/\/km/).first()).toBeVisible(); // pace value
  await expect(page.getByText(/bpm/).first()).toBeVisible(); // heart rate
  await expect(page.getByText(/kcal/).first()).toBeVisible(); // calories

  // The route map renders from the activity's polyline (RoutePreview svg).
  await expect(page.getByTestId("route-map")).toBeVisible();
});

test("the detail back button returns to the calendar on a direct load", async ({ page }) => {
  // Direct load / refresh: no in-app history to pop, so navigate(-1) would be a no-op.
  await page.goto("/workout/1");
  await page.locator("header button").click();
  await expect(page).toHaveURL(/\/calendar/);
});
