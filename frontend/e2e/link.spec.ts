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
