// Takes the review screenshots into docs/screenshots/<scene>-<width>-<theme>.png.
// Run with: npm run screenshots   (it deletes the old PNGs first, so no stale files remain)
// or:       SCREENSHOTS=1 npx playwright test --project=screenshots
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUT = path.resolve(__dirname, "../../../docs/screenshots");
const SIZES = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];
const THEMES = ["dark", "light"] as const;

async function sendAndWait(page: Page, text: string) {
  await page.getByLabel("Message CampusPilot").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden({ timeout: 20_000 });
  await page.waitForTimeout(400);
}

/** Start a question but do not wait for the stream to end (for the frozen "streaming" scenes). */
async function sendOnly(page: Page, text: string) {
  await page.getByLabel("Message CampusPilot").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

/** Let fonts and animations finish, so every capture is stable. */
async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(350);
}

/** Capture with no stray focus ring, tooltip or hover state. */
async function shot(page: Page, name: string, width: number, theme: string, opts: { keepFocus?: boolean } = {}) {
  if (!opts.keepFocus) {
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
    await page.mouse.move(width - 3, 450); // an empty spot, away from every control
    await page.waitForTimeout(250); // tooltips close shortly after the pointer leaves
  }
  await settle(page);
  await page.screenshot({ path: path.join(OUT, `${name}-${width}-${theme}.png`) });
}

for (const size of SIZES) {
  for (const theme of THEMES) {
    test.describe(`${size.width} ${theme}`, () => {
      // The 390 px runs act like a phone (touch, no hover), so the "..." buttons show as they do on a real one.
      const phone = size.width < 500;
      test.use({ viewport: size, reducedMotion: "reduce", isMobile: phone, hasTouch: phone });

      test.beforeEach(async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem("campuspilot.theme", t), theme);
      });

      const open = async (page: Page, query = "") => {
        await page.goto(`/${query}`);
        await expect(page.getByRole("heading", { name: /What do you need/ })).toBeVisible();
        await page.waitForTimeout(500); // let the status pill settle
      };

      test("empty", async ({ page }) => {
        await open(page);
        await shot(page, "empty", size.width, theme);
      });

      test("answer-sources", async ({ page }) => {
        await open(page);
        await sendAndWait(page, "Academic calendar");
        // On the phone, show the top of the answer, with the table running under the composer fade.
        if (size.width < 500) await page.getByTestId("scroll-area").evaluate((el) => (el.scrollTop = 0));
        await shot(page, "answer-sources", size.width, theme);
      });

      // The one scene where a hover preview is meant to be open.
      test("citation-preview", async ({ page }) => {
        await open(page);
        await sendAndWait(page, "Academic calendar");
        await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.()); // no focus ring on the composer
        await page.getByRole("article").getByRole("link", { name: /^Source 1:/ }).hover();
        await page.waitForTimeout(400);
        await settle(page);
        await page.screenshot({ path: path.join(OUT, `citation-preview-${size.width}-${theme}.png`) });
      });

      test("deadlines", async ({ page }) => {
        await open(page);
        await sendAndWait(page, "What's due this week?");
        await page.getByTestId("scroll-area").evaluate((el) => (el.scrollTop = 0));
        await page.waitForTimeout(200);
        await shot(page, "deadlines", size.width, theme);
      });

      test("clarify", async ({ page }) => {
        await open(page);
        await sendAndWait(page, "Can I change my room?");
        await shot(page, "clarify", size.width, theme);
      });

      test("abstain", async ({ page }) => {
        await open(page);
        await sendAndWait(page, "What is the 2031 mess menu?");
        await shot(page, "abstain", size.width, theme);
      });

      test("offline", async ({ page }) => {
        await open(page, "?mockOffline=1");
        await sendAndWait(page, "Academic calendar");
        await expect(page.getByText("Retry status check")).toBeVisible();
        await shot(page, "offline", size.width, theme);
      });

      // A step is running: shimmer on the step, grey skeleton lines for the answer.
      test("streaming", async ({ page }) => {
        await open(page, "?mockHold=tool");
        await sendOnly(page, "Academic calendar");
        await expect(page.getByRole("list", { name: "Progress" })).toBeVisible();
        await page.waitForTimeout(300);
        await shot(page, "streaming", size.width, theme);
      });

      // Part-way through the text: the blinking caret.
      test("streaming-caret", async ({ page }) => {
        await open(page, "?mockHold=text");
        await sendOnly(page, "Academic calendar");
        await expect(page.getByRole("article")).toContainText("sample content", { timeout: 10_000 });
        await page.waitForTimeout(300);
        await shot(page, "streaming-caret", size.width, theme);
      });

      // The first word takes longer than 3 s: "Waking up the model".
      test("waking", async ({ page }) => {
        await open(page, "?mockWake=1");
        await sendOnly(page, "Academic calendar");
        await expect(page.getByText("Waking up the model")).toBeVisible({ timeout: 8_000 });
        await shot(page, "waking", size.width, theme);
      });

      test("settings", async ({ page }) => {
        await open(page);
        await page.getByRole("button", { name: /^Moodle/ }).click();
        await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
        await page.waitForTimeout(300);
        await shot(page, "settings", size.width, theme);
      });

      // ---------- hosted mode (bring-your-own-key), mock ----------
      const openHosted = async (page: Page, query = "", opts: { key?: boolean; provider?: string } = {}) => {
        if (opts.key) {
          await page.addInitScript((p) => {
            if (!sessionStorage.getItem("campuspilot.llm.v1")) sessionStorage.setItem("campuspilot.llm.v1", JSON.stringify({ provider: p, key: "testkey_abcdefghijklmnopqrstuvwxyz123456" }));
          }, opts.provider ?? "groq");
        }
        await page.goto(`/?mockHosted=1${query}`);
        await expect(page.getByRole("heading", { name: opts.key ? /What do you need/ : /runs on your own AI key/ })).toBeVisible();
        await page.waitForTimeout(500);
      };

      test("hosted-key-card", async ({ page }) => {
        await openHosted(page);
        await shot(page, "hosted-key-card", size.width, theme);
      });

      // Typed key, tested OK, the Gemini privacy note and the guide closed.
      test("hosted-key-card-tested", async ({ page }) => {
        await openHosted(page);
        const card = page.getByTestId("key-card");
        await card.getByLabel("AI provider").selectOption("gemini");
        await card.getByLabel(/API key/).fill("testkey-gemini-abcdefghijklmnopqrstuvwxyz");
        await card.getByRole("button", { name: "Show key" }).click();
        await card.getByRole("button", { name: "Test key" }).click();
        await expect(card.getByRole("status").filter({ hasText: "key works" })).toBeVisible();
        await shot(page, "hosted-key-card-tested", size.width, theme);
      });

      test("hosted-key-card-error", async ({ page }) => {
        await openHosted(page);
        const card = page.getByTestId("key-card");
        await card.getByLabel(/API key/).fill("badkey_abcdefghijklmnopqrstuvwxyz");
        await card.getByRole("button", { name: "Test key" }).click();
        await expect(card.getByRole("alert").filter({ hasText: "rejected" })).toBeVisible();
        await shot(page, "hosted-key-card-error", size.width, theme);
      });

      test("hosted-empty", async ({ page }) => {
        await openHosted(page, "", { key: true });
        await shot(page, "hosted-empty", size.width, theme);
      });

      test("hosted-settings", async ({ page }) => {
        await openHosted(page, "", { key: true });
        await page.getByTestId("provider-pill").click();
        await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();
        await page.waitForTimeout(300);
        await shot(page, "hosted-settings", size.width, theme);
      });

      test("hosted-settings-bottom", async ({ page }) => {
        await openHosted(page, "", { key: true });
        await page.getByTestId("provider-pill").click();
        const dialog = page.getByRole("dialog", { name: "Settings" });
        await dialog.getByLabel("Moodle calendar link").fill("mock-moodle-token-123456");
        await dialog.getByRole("button", { name: "Test Moodle" }).click();
        await expect(dialog.getByRole("status").filter({ hasText: "accepted" })).toBeVisible();
        await dialog.getByRole("switch", { name: "Remember on this device" }).last().click();
        await dialog.getByRole("button", { name: "Forget everything" }).click();
        await dialog.evaluate((el) => (el.scrollTop = el.scrollHeight));
        await page.waitForTimeout(300);
        await shot(page, "hosted-settings-bottom", size.width, theme);
      });

      test("hosted-error-rate-limit", async ({ page }) => {
        await openHosted(page, "&mockError=PROVIDER_RATE_LIMITED", { key: true });
        await sendAndWait(page, "Academic calendar");
        await expect(page.getByTestId("error-card")).toBeVisible();
        await shot(page, "hosted-error-rate-limit", size.width, theme);
      });

      test("hosted-error-key", async ({ page }) => {
        await openHosted(page, "&mockError=PROVIDER_KEY_REJECTED", { key: true });
        await sendAndWait(page, "Academic calendar");
        await expect(page.getByTestId("error-card")).toBeVisible();
        await shot(page, "hosted-error-key", size.width, theme);
      });

      test("hosted-waking", async ({ page }) => {
        await page.goto("/?mockHosted=1&mockCold=1");
        await expect(page.getByTestId("waking-notice")).toBeVisible({ timeout: 8_000 });
        await page.waitForTimeout(400);
        await shot(page, "hosted-waking", size.width, theme);
      });

      test("hosted-server-failed", async ({ page }) => {
        await page.goto("/?mockHosted=1&mockCold=fail");
        await expect(page.getByTestId("server-failed-notice")).toBeVisible({ timeout: 25_000 });
        await shot(page, "hosted-server-failed", size.width, theme);
      });

      test("hosted-moodle-answer", async ({ page }) => {
        await openHosted(page, "", { key: true });
        await sendAndWait(page, "What's due this week?");
        await page.getByTestId("scroll-area").evaluate((el) => (el.scrollTop = 0));
        await page.waitForTimeout(200);
        await shot(page, "hosted-moodle-answer", size.width, theme);
      });

      test("mobile-sidebar", async ({ page }) => {
        test.skip(size.width > 500, "mobile only");
        await open(page);
        await sendAndWait(page, "Academic calendar");
        await page.getByRole("button", { name: "Toggle sidebar" }).click();
        await page.getByRole("button", { name: "New chat" }).click();
        await sendAndWait(page, "What's due this week?");
        await page.getByRole("button", { name: "Toggle sidebar" }).click();
        await page.waitForTimeout(400);
        await shot(page, "mobile-sidebar", size.width, theme);
      });
    });
  }
}
