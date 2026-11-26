import { expect, test, type Page } from "@playwright/test";

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

// ---------- hosted mode (bring-your-own-key), in mock: /?mockHosted=1 ----------

const GOOD_KEY = "testkey_abcdefghijklmnopqrstuvwxyz123456";
const BAD_KEY = "badkey_abcdefghijklmnopqrstuvwxyz";

/** Pretend a key was saved earlier in this tab. */
async function withSavedKey(page: Page, provider = "groq") {
  await page.addInitScript(
    ([k, p]) => {
      if (!sessionStorage.getItem("campuspilot.llm.v1")) sessionStorage.setItem("campuspilot.llm.v1", JSON.stringify({ provider: p, key: k }));
    },
    [GOOD_KEY, provider],
  );
}

test("hosted: the key card shows when there is no key, and saving a key hides it and shows the pill", async ({ page }) => {
  await page.goto("/?mockHosted=1");
  const card = page.getByTestId("key-card");
  await expect(card.getByRole("heading", { name: "CampusPilot runs on your own AI key. It's free with Groq." })).toBeVisible();
  await expect(card.getByLabel("AI provider")).toHaveValue("groq");
  await expect(card.getByRole("option", { name: /Groq \(Recommended, free\)/ })).toBeAttached();
  await expect(page.getByLabel("Message CampusPilot")).toBeDisabled();

  // The key is masked until "Show key" is pressed.
  const field = card.getByLabel(/API key/);
  await field.fill(GOOD_KEY);
  await expect(field).toHaveAttribute("type", "password");
  await card.getByRole("button", { name: "Show key" }).click();
  await expect(field).toHaveAttribute("type", "text");

  await card.getByRole("button", { name: "Save and start chatting" }).click();
  await expect(card).toBeHidden();
  await expect(page.getByTestId("provider-pill")).toContainText("Groq · your key");
  await expect(page.getByRole("heading", { name: "What do you need on campus today?" })).toBeVisible();
  await expect(page.getByLabel("Message CampusPilot")).toBeEnabled();
  // Not remembered by default: the key is in sessionStorage only.
  expect(await page.evaluate(() => localStorage.getItem("campuspilot.llm.v1"))).toBeNull();
  expect(await page.evaluate(() => sessionStorage.getItem("campuspilot.llm.v1"))).toContain("groq");
});

test("hosted: Test key shows the friendly result inline, and a Gemini note appears", async ({ page }) => {
  await page.goto("/?mockHosted=1");
  const card = page.getByTestId("key-card");
  await card.getByLabel("AI provider").selectOption("gemini");
  await expect(card.getByText("Google's free tier may use your prompts to improve its products; Groq is recommended.")).toBeVisible();
  await card.getByLabel("AI provider").selectOption("groq");

  await card.getByLabel(/API key/).fill(BAD_KEY);
  await card.getByRole("button", { name: "Test key" }).click();
  await expect(card.getByRole("alert").filter({ hasText: "rejected" })).toBeVisible();

  await card.getByLabel(/API key/).fill(GOOD_KEY);
  await card.getByRole("button", { name: "Test key" }).click();
  await expect(card.getByRole("status").filter({ hasText: "key works" })).toBeVisible();
});

test("hosted: a short key is refused before anything is sent", async ({ page }) => {
  await page.goto("/?mockHosted=1");
  const card = page.getByTestId("key-card");
  await card.getByLabel(/API key/).fill("too-short");
  await card.getByRole("button", { name: "Save and start chatting" }).click();
  await expect(card.getByRole("alert")).toContainText("doesn't look like an API key");
});

test("hosted: Forget everything brings the key card back", async ({ page }) => {
  await withSavedKey(page);
  await page.goto("/?mockHosted=1");
  await expect(page.getByTestId("provider-pill")).toContainText("Groq · your key");
  await page.getByRole("button", { name: "Academic calendar" }).click();
  await expect(page.getByRole("article", { name: "Assistant answer" })).toContainText("official academic calendar", { timeout: 15_000 });

  await page.getByTestId("provider-pill").click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByRole("heading", { name: "1. Model key" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "2. Moodle" })).toBeVisible();
  await dialog.getByRole("button", { name: "Forget everything" }).click();
  await dialog.getByRole("button", { name: "Yes, forget everything" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByTestId("key-card")).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem("campuspilot.llm.v1"))).toBeNull();
  expect(await page.evaluate(() => localStorage.getItem("campuspilot.conversations.v1"))).toBeNull();
});

test("hosted: Remember on this device moves the key to localStorage and back", async ({ page }) => {
  await withSavedKey(page);
  await page.goto("/?mockHosted=1");
  await page.getByTestId("provider-pill").click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  const sw = dialog.getByRole("switch", { name: "Remember on this device" }).first();
  await expect(sw).toHaveAttribute("aria-checked", "false");
  await sw.click();
  await expect(sw).toHaveAttribute("aria-checked", "true");
  expect(await page.evaluate(() => localStorage.getItem("campuspilot.llm.v1"))).toContain("groq");
  expect(await page.evaluate(() => sessionStorage.getItem("campuspilot.llm.v1"))).toBeNull();
  await sw.click();
  expect(await page.evaluate(() => localStorage.getItem("campuspilot.llm.v1"))).toBeNull();
  expect(await page.evaluate(() => sessionStorage.getItem("campuspilot.llm.v1"))).toContain("groq");
});

test("hosted: settings validate the model override and the Moodle link", async ({ page }) => {
  await withSavedKey(page);
  await page.goto("/?mockHosted=1");
  await page.getByTestId("provider-pill").click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await dialog.getByRole("button", { name: "Advanced: use a different model" }).click();
  await dialog.getByLabel(/Model override/).fill("bad model!");
  await dialog.getByRole("button", { name: "Test key" }).click();
  await expect(dialog.getByRole("alert").filter({ hasText: "Model names use" })).toBeVisible();

  await dialog.getByLabel("Moodle token or iCal link").fill("https://evil.example.com/cal.ics");
  await dialog.getByRole("button", { name: "Test Moodle" }).click();
  await expect(dialog.getByRole("alert").filter({ hasText: "https://moodle.iitb.ac.in/" })).toBeVisible();

  await dialog.getByLabel("Moodle token or iCal link").fill("https://moodle.iitb.ac.in/calendar/export_execute.php?userid=1&authtoken=abc");
  await dialog.getByRole("button", { name: "Test Moodle" }).click();
  await expect(dialog.getByRole("status").filter({ hasText: "accepted" })).toBeVisible();
  await expect(dialog.getByText("never sent to the AI model")).toBeVisible();
});

test("hosted: a provider error renders a banner that names the provider, with Change key", async ({ page }) => {
  await withSavedKey(page);
  await page.goto("/?mockHosted=1&mockError=PROVIDER_RATE_LIMITED");
  await page.getByRole("button", { name: "Academic calendar" }).click();
  const card = page.getByTestId("error-card");
  await expect(card).toHaveAttribute("data-code", "PROVIDER_RATE_LIMITED");
  await expect(card).toContainText("Groq");
  await expect(card).toContainText(/try again in \d+ s/i);
  await expect(card.getByRole("button", { name: "Try again" })).toBeDisabled(); // waiting out the limit
  await card.getByRole("button", { name: "Change key" }).click();
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
});

test("hosted: a rejected key maps to Change key too (HTTP 401 path)", async ({ page }) => {
  await withSavedKey(page, "gemini");
  await page.goto("/?mockHosted=1&mockError=PROVIDER_KEY_REJECTED");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  const card = page.getByTestId("error-card");
  await expect(card).toContainText("Google Gemini");
  await expect(card.getByRole("button", { name: "Change key" })).toBeVisible();
});

test("hosted: MODEL_KEY_REQUIRED opens the key settings", async ({ page }) => {
  await withSavedKey(page);
  await page.goto("/?mockHosted=1&mockError=MODEL_KEY_REQUIRED");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  await page.getByTestId("error-card").getByRole("button", { name: "Add key" }).click();
  await expect(page.getByRole("dialog", { name: "Settings" }).getByLabel(/API key/)).toBeVisible();
});

test("hosted: a sleeping server shows the waking notice, then a retry button", async ({ page }) => {
  await page.goto("/?mockHosted=1&mockCold=fail");
  await expect(page.getByTestId("waking-notice")).toContainText("Waking the server", { timeout: 8_000 });
  const failed = page.getByTestId("server-failed-notice");
  await expect(failed).toBeVisible({ timeout: 20_000 });
  await expect(failed.getByRole("button", { name: "Retry" })).toBeVisible();
});

test("hosted: a Moodle answer shows deadline cards from a template sentence, with no citation chips", async ({ page }) => {
  await withSavedKey(page);
  await page.goto("/?mockHosted=1");
  await page.getByRole("button", { name: "What's due this week?" }).click();
  await expect(page.getByRole("region", { name: "Deadlines" })).toBeVisible({ timeout: 15_000 });
  const answer = page.getByRole("article", { name: "Assistant answer" });
  await expect(answer).toContainText("You have 6 deadlines in the next 7 days");
  await expect(answer.getByRole("link", { name: /^Source / })).toHaveCount(0);
});

test("local mode keeps today's UI: no key card, model status pill", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("key-card")).toHaveCount(0);
  await expect(page.getByTestId("status-pill")).toBeVisible();
  await expect(page.getByTestId("provider-pill")).toHaveCount(0);
});

test("security: the page is served with a nonce CSP and the other security headers", async ({ page }) => {
  const res = await page.goto("/");
  const h = res!.headers();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["content-security-policy"]).toContain("object-src 'none'");
  expect(h["content-security-policy"]).toContain("base-uri 'self'");
  expect(h["content-security-policy"]).toMatch(/connect-src 'self' http:\/\/127\.0\.0\.1:8000/);
  expect(h["content-security-policy"]).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'(?!.*unsafe-eval)/);
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("no-referrer");
  // The app still works under the policy.
  await expect(page.getByRole("heading", { name: "What do you need on campus today?" })).toBeVisible();
});
