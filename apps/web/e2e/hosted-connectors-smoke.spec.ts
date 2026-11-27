import { expect, test, type Page } from "@playwright/test";

// Hosted mode (mock): Settings -> Connectors is a guide only. It must make no connector request and ask for no login.

const GOOD_KEY = "testkey_abcdefghijklmnopqrstuvwxyz123456";

async function openHostedSettings(page: Page, seen?: string[]) {
  if (seen) {
    page.on("request", (r) => {
      const p = new URL(r.url()).pathname;
      if (p.startsWith("/v1/connectors") || p.startsWith("/v1/calendar")) seen.push(`${r.method()} ${p}`);
    });
  }
  await page.addInitScript((k) => {
    if (!sessionStorage.getItem("campuspilot.llm.v1")) sessionStorage.setItem("campuspilot.llm.v1", JSON.stringify({ provider: "groq", key: k }));
  }, GOOD_KEY);
  await page.goto("/?mockHosted=1");
  await page.getByTestId("provider-pill").click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog).toBeVisible();
  return dialog;
}

test("hosted Settings: same section order as local, with a Connectors guide", async ({ page }) => {
  const dialog = await openHostedSettings(page);
  const names = await dialog.getByRole("heading", { level: 3 }).allTextContents();
  expect(names).toEqual(["AI key", "Moodle", "Connectors", "Model status", "Local data"]);
  await expect(dialog.getByText("Moodle works here: paste your Moodle calendar link")).toBeVisible();
  for (const id of ["webmail", "asc", "gcal"]) {
    const card = dialog.getByTestId(`hosted-connector-${id}`);
    await expect(card).toBeVisible();
    await expect(card.getByText("Local app only")).toBeVisible();
    await expect(card.getByText(/never stores your/)).toBeVisible();
    // No login form for a connector in hosted mode.
    await expect(card.getByRole("textbox")).toHaveCount(0);
    await expect(card.getByLabel(/password/i)).toHaveCount(0);
  }
  // Existing hosted controls are still there.
  await expect(dialog.getByRole("button", { name: "Forget everything" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Test key" })).toBeVisible();
});

test("hosted Connectors: How to connect expands the numbered steps for each connector", async ({ page }) => {
  const dialog = await openHostedSettings(page);

  const webmail = dialog.getByTestId("hosted-connector-webmail");
  const toggle = webmail.getByRole("button", { name: "How to connect" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(webmail.getByRole("list")).toHaveCount(0);
  await toggle.focus();
  await page.keyboard.press("Enter"); // keyboard operable
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(webmail.getByRole("listitem").first()).toContainText("git clone https://github.com/biprabhanu/iitb-campus-assistant");
  await expect(webmail).toContainText("make setup");
  await expect(webmail).toContainText("WEBMAIL_ENABLED=true");
  await expect(webmail).toContainText("make dev");
  await expect(webmail).toContainText("http://127.0.0.1:3000");
  await expect(webmail).toContainText("Access tokens");
  await expect(webmail).toContainText("not your LDAP password");
  await expect(webmail).toContainText("Keychain");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");

  const asc = dialog.getByTestId("hosted-connector-asc");
  await asc.getByRole("button", { name: "How to connect" }).click();
  await expect(asc).toContainText("ASC_ENABLED=true");
  await expect(asc).toContainText("campus network or the IITB VPN");
  await expect(asc).toContainText("LDAP password");
  await expect(asc).toContainText("Grades are never read");
  await expect(asc).toContainText("only the local model");

  const gcal = dialog.getByTestId("hosted-connector-gcal");
  await gcal.getByRole("button", { name: "How to connect" }).click();
  await expect(gcal).toContainText("GCAL_ENABLED=true");
  await expect(gcal).toContainText("Desktop app");
  await expect(gcal).toContainText("~/.campuspilot/google_client.json");
  await expect(gcal).toContainText("only when you click Add");
});

test("hosted Connectors: links open in a new tab with noopener noreferrer", async ({ page }) => {
  const dialog = await openHostedSettings(page);
  const webmail = dialog.getByTestId("hosted-connector-webmail");
  await webmail.getByRole("button", { name: "How to connect" }).click();
  await dialog.getByTestId("hosted-connector-gcal").getByRole("button", { name: "How to connect" }).click();

  const github = webmail.getByRole("link", { name: "GitHub" });
  await expect(github).toHaveAttribute("href", "https://github.com/biprabhanu/iitb-campus-assistant");
  await expect(github).toHaveAttribute("target", "_blank");
  await expect(github).toHaveAttribute("rel", "noopener noreferrer");
  await expect(webmail.getByRole("link", { name: "sso.iitb.ac.in" })).toHaveAttribute("href", "https://sso.iitb.ac.in");

  // Every external link inside the Connectors section opens safely.
  const links = dialog.getByTestId(/^hosted-connector-/).getByRole("link");
  const n = await links.count();
  expect(n).toBeGreaterThanOrEqual(4);
  for (let i = 0; i < n; i++) {
    await expect(links.nth(i)).toHaveAttribute("target", "_blank");
    await expect(links.nth(i)).toHaveAttribute("rel", "noopener noreferrer");
  }
});

test("hosted mode sends no connector or calendar request, even after opening every guide", async ({ page }) => {
  const seen: string[] = [];
  const dialog = await openHostedSettings(page, seen);
  for (const id of ["webmail", "asc", "gcal"]) {
    await dialog.getByTestId(`hosted-connector-${id}`).getByRole("button", { name: "How to connect" }).click();
  }
  await page.waitForTimeout(500);
  expect(seen).toEqual([]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`390 px (${scheme}): hosted Settings with open guides has no sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ colorScheme: scheme });
    const dialog = await openHostedSettings(page);
    for (const id of ["webmail", "asc", "gcal"]) {
      await dialog.getByTestId(`hosted-connector-${id}`).getByRole("button", { name: "How to connect" }).click();
    }
    await dialog.getByTestId("hosted-connector-gcal").scrollIntoViewIfNeeded();
    expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    for (const card of await dialog.getByTestId(/^hosted-connector-/).all()) {
      const box = await card.boundingBox();
      expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    }
  });
}
