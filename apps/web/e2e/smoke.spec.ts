import { expect, test } from "@playwright/test";

test("suggestion shows sources and an answer with a citation chip", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "What do you need on campus today?" })).toBeVisible();

  await page.getByRole("button", { name: "Academic calendar" }).click();

  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByRole("link")).toHaveCount(2);

  const answer = page.getByRole("article", { name: "Assistant answer" });
  await expect(answer).toContainText("official academic calendar", { timeout: 15_000 });
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

test("steps fold into one quiet line once the answer is done", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  const steps = page.getByRole("button", { name: /Searched campus documents/ });
  await expect(steps).toBeVisible({ timeout: 15_000 });
  await expect(steps).toHaveAttribute("aria-expanded", "false");
  await steps.click();
  await expect(steps).toHaveAttribute("aria-expanded", "true");
});

test("offline status shows a notice with a retry button", async ({ page }) => {
  await page.goto("/?mockOffline=1");
  await expect(page.getByText("answers will fail until the tunnel is back")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry status check" })).toBeVisible();
});

test("citation preview opens from the keyboard", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  const chip = page.getByRole("article").getByRole("link", { name: /^Source 1:/ });
  await expect(chip).toBeVisible({ timeout: 15_000 });
  await chip.focus();
  await expect(page.getByRole("tooltip").getByText("Open source")).toBeVisible();
});

test("mobile drawer: focus stays inside, Escape closes it", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  const drawer = page.getByRole("dialog", { name: "Chat history" });
  await expect(drawer).toBeVisible();
  await expect(page.getByRole("button", { name: "Close sidebar" })).toBeFocused();
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    expect(await drawer.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("chat list: the ... menu offers rename and delete", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  await page.getByRole("button", { name: /^Options for/ }).click();
  await expect(page.getByRole("menuitem", { name: "Rename" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: "Delete" })).toBeVisible();
});
