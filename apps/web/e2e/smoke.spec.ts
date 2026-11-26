import { expect, test } from "@playwright/test";

test("suggestion shows sources and an answer with a citation chip", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What do you need on campus today?" })).toBeVisible();

  await page.getByRole("button", { name: "Academic calendar" }).click();

  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByRole("link")).toHaveCount(2);

  const answer = page.getByRole("article", { name: "Assistant answer" });
  await expect(answer).toContainText("2026-27 academic calendar", { timeout: 15_000 });
  // Citation chips appear once the stream is done and the ids are validated.
  await expect(answer.getByRole("link", { name: /^Source 1:/ })).toBeVisible({ timeout: 15_000 });
  await expect(answer.locator("table")).toBeVisible();
});

test("an unvalidated marker never renders", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  const answer = page.getByRole("article", { name: "Assistant answer" });
  await expect(answer.getByRole("link", { name: /^Source 1:/ })).toBeVisible({ timeout: 15_000 });
  await expect(answer).not.toContainText("[S1]");
});
