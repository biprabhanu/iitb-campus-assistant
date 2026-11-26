// Review screenshots for the v2 connectors, written to docs/screenshots/v2-<scene>-<width>-<theme>.png
// (or to $SHOT_DIR while polishing). It only ever writes v2-* files; the older PNGs are never touched.
// Run with: SCREENSHOTS=1 npx playwright test --project=screenshots e2e/v2-screenshots.spec.ts
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const OUT = process.env.SHOT_DIR ?? path.resolve(__dirname, "../../../docs/screenshots");
const SIZES = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];
const THEMES = ["dark", "light"] as const;

async function ask(page: Page, text: string) {
  await page.getByLabel("Message CampusPilot").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden({ timeout: 20_000 });
  await page.waitForTimeout(400);
}

async function shot(page: Page, name: string, width: number, theme: string) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
  await page.mouse.move(width - 3, 450);
  await page.waitForTimeout(250);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  await page.screenshot({ path: path.join(OUT, `v2-${name}-${width}-${theme}.png`) });
}

const toTop = (page: Page) => page.getByTestId("scroll-area").evaluate((el) => (el.scrollTop = 0));

for (const size of SIZES) {
  for (const theme of THEMES) {
    test.describe(`${size.width} ${theme}`, () => {
      const phone = size.width < 500;
      test.use({ viewport: size, reducedMotion: "reduce", isMobile: phone, hasTouch: phone });

      test.beforeEach(async ({ page }) => {
        await page.addInitScript((t) => localStorage.setItem("campuspilot.theme", t), theme);
      });

      const open = async (page: Page, query = "") => {
        await page.goto(`/${query}`);
        await expect(page.getByRole("heading", { name: /What do you need/ })).toBeVisible();
        await page.waitForTimeout(500);
      };

      const openSettings = async (page: Page) => {
        if (phone) await page.getByRole("button", { name: "Toggle sidebar" }).click();
        await page.getByRole("button", { name: "Settings", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: "Settings" });
        await expect(dialog.getByTestId("connector-gcal")).toBeVisible();
        return dialog;
      };

      test("events", async ({ page }) => {
        await open(page, "?mockConnectors=connected");
        await ask(page, "Any institute events this week from my mail?");
        await toTop(page);
        await shot(page, "events", size.width, theme);
      });

      test("event-added", async ({ page }) => {
        await open(page, "?mockConnectors=connected");
        await ask(page, "Any institute events this week from my mail?");
        await page.getByRole("button", { name: "Add to Google Calendar" }).first().click();
        await expect(page.getByText("Added ✓")).toBeVisible();
        await toTop(page);
        await shot(page, "event-added", size.width, theme);
      });

      test("events-connect", async ({ page }) => {
        await open(page);
        await ask(page, "Any institute events this week from my mail?");
        await expect(page.getByRole("button", { name: "Connect Google Calendar" }).first()).toBeVisible();
        await toTop(page);
        await shot(page, "events-connect", size.width, theme);
      });

      test("timetable", async ({ page }) => {
        await open(page);
        await ask(page, "What's my timetable tomorrow?");
        await toTop(page);
        await shot(page, "timetable", size.width, theme);
      });

      test("grades-hidden", async ({ page }) => {
        await open(page);
        await ask(page, "What are my grades?");
        await toTop(page);
        await shot(page, "grades-hidden", size.width, theme);
      });

      test("grades-shown", async ({ page }) => {
        await open(page);
        await ask(page, "What are my grades?");
        await page.getByRole("button", { name: "Show grades" }).click();
        await toTop(page);
        await shot(page, "grades-shown", size.width, theme);
      });

      test("courses", async ({ page }) => {
        await open(page);
        await ask(page, "Which are my registered courses?");
        await toTop(page);
        await shot(page, "courses", size.width, theme);
      });

      test("mail", async ({ page }) => {
        await open(page);
        await ask(page, "Search my mail");
        await toTop(page);
        await shot(page, "mail", size.width, theme);
      });

      test("due-mixed", async ({ page }) => {
        await open(page, "?mockConnectors=connected");
        await ask(page, "What's due this week?");
        await toTop(page);
        await shot(page, "due-mixed", size.width, theme);
      });

      test("sources-label", async ({ page }) => {
        await open(page);
        await ask(page, "Academic calendar");
        await toTop(page);
        await shot(page, "sources-label", size.width, theme);
      });

      test("settings-connectors", async ({ page }) => {
        await open(page);
        const dialog = await openSettings(page);
        await dialog.getByRole("heading", { name: "Connectors" }).scrollIntoViewIfNeeded();
        await page.waitForTimeout(300);
        await shot(page, "settings-connectors", size.width, theme);
      });

      test("settings-otp", async ({ page }) => {
        await open(page);
        const dialog = await openSettings(page);
        const card = dialog.getByTestId("connector-asc");
        await card.getByRole("button", { name: "Connect ASC" }).click();
        await card.getByLabel("IITB LDAP username").fill("demo.student");
        await card.getByLabel("LDAP password").fill("fake-password");
        await card.getByRole("button", { name: "Connect", exact: true }).click();
        await expect(card.getByLabel("One-time code")).toBeVisible();
        await card.scrollIntoViewIfNeeded();
        await page.waitForTimeout(300);
        await shot(page, "settings-otp", size.width, theme);
      });

      // The Webmail form: LDAP ID plus an SSO access token (IITB mail does not take the LDAP password).
      test("settings-webmail-form", async ({ page }) => {
        await open(page);
        const dialog = await openSettings(page);
        const card = dialog.getByTestId("connector-webmail");
        await card.getByRole("button", { name: "Connect IITB Webmail" }).click();
        await card.scrollIntoViewIfNeeded();
        await page.waitForTimeout(300);
        await shot(page, "settings-webmail-form", size.width, theme);
      });

      test("settings-connected", async ({ page }) => {
        await open(page, "?mockConnectors=connected");
        const dialog = await openSettings(page);
        await dialog.getByRole("heading", { name: "Connectors" }).scrollIntoViewIfNeeded();
        await page.waitForTimeout(300);
        await shot(page, "settings-connected", size.width, theme);
      });

      test("settings-off", async ({ page }) => {
        await open(page, "?mockConnectors=off");
        const dialog = await openSettings(page);
        await dialog.getByRole("heading", { name: "Connectors" }).scrollIntoViewIfNeeded();
        await page.waitForTimeout(300);
        await shot(page, "settings-off", size.width, theme);
      });
    });
  }
}
