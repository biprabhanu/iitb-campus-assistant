// Takes the review screenshots into docs/screenshots/<name>-<width>-<theme>.png.
// Run with: SCREENSHOTS=1 npx playwright test --project=screenshots
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

async function shot(page: Page, name: string, width: number, theme: string) {
  await page.screenshot({ path: path.join(OUT, `${name}-${width}-${theme}.png`) });
}

for (const size of SIZES) {
  for (const theme of THEMES) {
    test.describe(`${size.width} ${theme}`, () => {
      test.use({ viewport: size, reducedMotion: "reduce" });

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
        await page.getByRole("article").getByRole("link", { name: /^Source 1:/ }).hover();
        await page.waitForTimeout(300);
        await shot(page, "answer-sources", size.width, theme);
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
        await shot(page, "offline", size.width, theme);
      });

      test("mobile-sidebar", async ({ page }) => {
        test.skip(size.width > 500, "mobile only");
        await open(page);
        await sendAndWait(page, "Academic calendar");
        await page.getByRole("button", { name: "Toggle sidebar" }).click();
        await page.waitForTimeout(400);
        await shot(page, "mobile-sidebar", size.width, theme);
      });
    });
  }
}
