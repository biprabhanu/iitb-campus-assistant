// v2 connectors: answer cards (mail events and the ASC views) and Settings -> Connectors.
// The chat stream is always the built-in mock. Most tests use the in-memory connector mock
// (?mockConnectors=...). The ones that must see real requests add ?mockNet=1 and answer them with
// page.route, so we can check the URL, the X-CampusPilot-Confirm header and the body.
// Nothing here is a real account: every name, password and code is made up.
import { expect, test, type Page, type Request, type Route } from "@playwright/test";

const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "GET,POST,DELETE,OPTIONS" };

const LOCAL_STATUS = {
  model_online: true,
  model_loaded: true,
  model: "mock",
  moodle: "connected",
  moodle_mode: "demo",
  sources_indexed: 24,
  mode: "mock",
  deploy_mode: "local",
  connectors: ["webmail", "asc", "gcal"],
};

const status = (name: string, state: string, extra: Record<string, unknown> = {}) => ({ name, enabled: state !== "disabled", state, ...extra });

/** Answer a route (and its CORS preflight) with JSON. */
async function json(route: Route, body: unknown, httpStatus = 200) {
  if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers: CORS });
  return route.fulfill({ status: httpStatus, headers: CORS, contentType: "application/json", body: JSON.stringify(body) });
}

/** The UI uses real fetch for status, ping and connectors (?mockNet=1); these are the fakes. */
async function fakeApi(page: Page, opts: { status?: object; connectors?: object } = {}) {
  await page.route("**/v1/ping", (r) => json(r, { ok: true }));
  await page.route("**/v1/status", (r) => json(r, opts.status ?? LOCAL_STATUS));
  await page.route("**/v1/connectors", (r) =>
    json(r, opts.connectors ?? { webmail: status("webmail", "not_connected"), asc: status("asc", "not_connected"), gcal: status("gcal", "connected", { account: "demo.student@example.com" }) }),
  );
}

async function ask(page: Page, text: string) {
  // A follow-up question waits until the previous answer has finished streaming.
  await expect(page.getByRole("button", { name: "Stop generating" })).toBeHidden({ timeout: 20_000 });
  await page.getByLabel("Message CampusPilot").fill(text);
  await page.getByRole("button", { name: "Send message" }).click();
}

async function openSettings(page: Page) {
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  return page.getByRole("dialog", { name: "Settings" });
}

// ---------- answer cards ----------

test("mail events: two labelled event cards, one can be added and one has an unclear date", async ({ page }) => {
  await page.goto("/?mockConnectors=connected");
  await ask(page, "Any institute events this week from my mail?");

  const events = page.getByRole("region", { name: "Events from your mail" });
  const cards = events.getByTestId("event-card");
  await expect(cards).toHaveCount(2, { timeout: 15_000 });
  for (const label of await events.getByTestId("source-label").allTextContents()) expect(label).toBe("Webmail");

  const [clear, unclear] = [cards.nth(0), cards.nth(1)];
  await expect(clear).toContainText("Guest talk: Analytics in supply chains");
  await expect(clear).toContainText("Talk");
  await expect(clear).toContainText("IST"); // times are shown in IST
  await expect(clear).toContainText("Lecture Hall 3");
  await expect(clear).toContainText("From: Student Events Cell");
  await expect(clear.getByRole("button", { name: "Add to Google Calendar" })).toBeEnabled();
  await expect(clear.getByRole("link", { name: /From: Student Events Cell/ })).toHaveAttribute("href", "https://webmail.iitb.ac.in/");

  await expect(unclear).toContainText("Date unclear — check the mail");
  await expect(unclear).toContainText("later this month");
  await expect(unclear).toContainText("Low confidence");
  await expect(unclear.getByRole("button", { name: "Add to Google Calendar" })).toHaveCount(0);
  await expect(unclear.getByRole("button", { name: "Date unclear" })).toBeDisabled();

  // The answer is a template sentence: no citation chips.
  await expect(page.getByRole("article").getByRole("link", { name: /^Source / })).toHaveCount(0);
});

test("Add to Google Calendar sends exactly one confirmed POST, then shows Added and View in Calendar", async ({ page }) => {
  const posts: Request[] = [];
  await fakeApi(page);
  await page.route("**/v1/calendar/events", (r) => {
    if (r.request().method() === "POST") posts.push(r.request());
    return json(r, { ok: true, status: "created", google_event_id: "g1", html_link: "https://calendar.google.com/calendar/event?eid=g1", message: "Added." });
  });
  await page.goto("/?mockNet=1&mockConnectors=connected");
  await ask(page, "Any institute events this week from my mail?");

  const card = page.getByTestId("event-card").first();
  const add = card.getByRole("button", { name: "Add to Google Calendar" });
  await add.dblclick(); // a double click must still be one request
  await expect(card).toContainText("Added ✓");
  await expect(card.getByRole("link", { name: /View in Calendar/ })).toHaveAttribute("href", "https://calendar.google.com/calendar/event?eid=g1");
  await expect(card.getByRole("button", { name: /Add to Google Calendar/ })).toHaveCount(0);

  expect(posts).toHaveLength(1);
  expect(posts[0].headers()["x-campuspilot-confirm"]).toBe("yes");
  const body = posts[0].postDataJSON();
  expect(body).toMatchObject({ title: "Guest talk: Analytics in supply chains", all_day: false });
  expect(body.start).toMatch(/\+05:30$/);
  expect(Object.keys(body).sort()).toEqual(["all_day", "end", "event_id", "mail_subject", "message_id", "start", "title", "venue"]);
});

test("Add: an error shows inline with a retry, and an existing event says so", async ({ page }) => {
  let calls = 0;
  await fakeApi(page);
  await page.route("**/v1/calendar/events", (r) => {
    if (r.request().method() === "OPTIONS") return json(r, null);
    calls++;
    if (calls === 1) return json(r, { code: "CALENDAR_ERROR", message: "Google couldn't add that event right now." }, 502);
    return json(r, { ok: true, status: "already_exists", google_event_id: "g1", html_link: "https://calendar.google.com/calendar/event?eid=g1", message: "Already there." });
  });
  await page.goto("/?mockNet=1&mockConnectors=connected");
  await ask(page, "Any institute events this week from my mail?");

  const card = page.getByTestId("event-card").first();
  await card.getByRole("button", { name: "Add to Google Calendar" }).click();
  await expect(card).toContainText("Google couldn't add that event right now.");
  await card.getByRole("button", { name: "Try again" }).click();
  await expect(card).toContainText("Already in your calendar");
  expect(calls).toBe(2);
});

test("with Google Calendar not connected, the card offers Connect and it opens Settings -> Connectors", async ({ page }) => {
  await page.goto("/"); // mock default: nothing connected
  await ask(page, "Any institute events this week from my mail?");
  const card = page.getByTestId("event-card").first();
  await expect(card.getByRole("button", { name: "Add to Google Calendar" })).toHaveCount(0);
  await card.getByRole("button", { name: "Connect Google Calendar" }).click();
  const dialog = page.getByRole("dialog", { name: "Settings" });
  await expect(dialog.getByRole("heading", { name: "Connectors" })).toBeFocused();
  await expect(dialog.getByTestId("connector-gcal")).toContainText("Not connected");
});

test("timetable: slots grouped under the day, each with course, venue and an ASC label", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What's my timetable tomorrow?");
  const table = page.getByRole("region", { name: "Timetable" });
  await expect(table.getByTestId("slot-card")).toHaveCount(3, { timeout: 15_000 });
  await expect(table.getByRole("heading", { name: "Tomorrow" })).toBeVisible();
  await expect(table.getByTestId("slot-card").first()).toContainText("IE 624");
  await expect(table.getByTestId("slot-card").first()).toContainText("9:30 AM");
  await expect(table.getByTestId("slot-card").first()).toContainText("LH 301");
  await expect(table.getByTestId("slot-card").first()).toContainText("Prof. A. Sample"); // the instructor
  expect(await table.getByTestId("source-label").allTextContents()).toEqual(["ASC", "ASC", "ASC"]);
  await expect(page.getByRole("article")).toContainText("You have 3 classes tomorrow");
});

test("current courses show code, title, credits, slot, instructor and the extra ASC fields", async ({ page }) => {
  await page.goto("/");
  await ask(page, "Which are my registered courses?");
  const courses = page.getByRole("region", { name: "Courses" }).getByTestId("course-card");
  await expect(courses).toHaveCount(4, { timeout: 15_000 });
  await expect(courses.first()).toContainText("6 credits");
  await expect(courses.first()).toContainText("Slot 1");
  await expect(courses.first()).toContainText("Prof. A. Sample");
  await expect(courses.first()).toContainText("Tag DC");
  await expect(courses.first()).toContainText("Credit");
  await expect(courses.first()).toContainText("LH 301");
  await expect(courses.first()).toContainText("registered");
  await expect(courses.last()).toContainText("audit");
  expect(new Set(await courses.getByTestId("source-label").allTextContents())).toEqual(new Set(["ASC"]));
  // A short list has no "Show all" toggle.
  await expect(page.getByRole("button", { name: /Show all/ })).toHaveCount(0);
});

test("registration status with the window closed lists the registered courses", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What is my registration status?");
  await expect(page.getByTestId("course-card")).toHaveCount(3, { timeout: 15_000 });
  await expect(page.getByRole("article")).toContainText("registration window is closed");
  await expect(page.getByRole("article").getByText("Checked your ASC registration")).toBeVisible();
});

test("fee status: a status chip with the word (paid is success, due is warning), amount and due date", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What is my fee status?");
  const fees = page.getByRole("region", { name: "Fee status" }).getByTestId("fee-card");
  await expect(fees).toHaveCount(3, { timeout: 15_000 });
  await expect(fees.nth(0)).toContainText("Tuition fee");
  await expect(fees.nth(0).getByTestId("fee-status")).toHaveText("Paid");
  await expect(fees.nth(0).getByTestId("fee-status")).toHaveClass(/text-success/);
  await expect(fees.nth(1).getByTestId("fee-status")).toHaveText("Due");
  await expect(fees.nth(1).getByTestId("fee-status")).toHaveClass(/text-warning/);
  await expect(fees.nth(1)).toContainText("Rs 3,000");
  await expect(fees.nth(1)).toContainText("Due 15 Dec 2026");
  expect(new Set(await fees.getByTestId("source-label").allTextContents())).toEqual(new Set(["ASC"]));
});

test("profile card shows department, program, status, validity, standing and advisors", async ({ page }) => {
  await page.goto("/");
  await ask(page, "Show my profile");
  const card = page.getByTestId("profile-card");
  await expect(card).toBeVisible({ timeout: 15_000 });
  await expect(card).toContainText("Industrial Engineering and Operations Research");
  await expect(card).toContainText("Master of Technology (sample)");
  await expect(card).toContainText("Registered");
  await expect(card).toContainText("2028-29 Spring");
  await expect(card).toContainText("Good standing");
  await expect(card).toContainText("Prof. A. Sample, Prof. B. Sample");
  await expect(card.getByTestId("source-label")).toHaveText("ASC");
});

test("offered courses: 14 rows show the first 10 with Show all 14, which expands and collapses", async ({ page }) => {
  await page.goto("/");
  await ask(page, "Which IE courses are offered in autumn 2026?");
  const courses = page.getByRole("region", { name: "Courses" }).getByTestId("course-card");
  await expect(courses).toHaveCount(10, { timeout: 15_000 });
  await expect(courses.first()).toContainText("Division 1"); // the extra fields: course type, venue, division
  await expect(courses.first()).toContainText("Core");
  const toggle = page.getByRole("button", { name: "Show all 14" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(courses).toHaveCount(14);
  await expect(page.getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("button", { name: "Show fewer" }).click();
  await expect(courses).toHaveCount(10);
});

test("offering history: a year x semester grid that says Offered / Not offered in words", async ({ page }) => {
  await page.goto("/");
  await ask(page, "When is IE 307 offered?");
  const card = page.getByTestId("history-card");
  await expect(card).toBeVisible({ timeout: 15_000 });
  await expect(card).toContainText("IE 307");
  await expect(card.getByRole("columnheader", { name: "Autumn" })).toBeVisible();
  await expect(card.getByRole("columnheader", { name: "Spring" })).toBeVisible();
  await expect(card.getByRole("rowheader")).toHaveText(["2026-27", "2025-26", "2024-25", "2023-24"]);
  await expect(card.getByTestId("offered")).toHaveCount(4);
  await expect(card.getByTestId("not-offered")).toHaveCount(4);
  await expect(card.getByTestId("offered").first()).toHaveText("Offered");
  await expect(card.getByTestId("not-offered").first()).toHaveText("Not offered");
  await expect(card.getByTestId("source-label")).toHaveText("ASC");
});

test("course details: prerequisites as chips, syllabus folded until Show syllabus", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What are the prerequisites of IE 307?");
  const card = page.getByTestId("detail-card");
  await expect(card).toBeVisible({ timeout: 15_000 });
  await expect(card).toContainText("IE 307");
  await expect(card).toContainText("6 credits");
  await expect(card.getByTestId("prereq")).toHaveText(["MA 106", "IE 201"]);
  await expect(card.getByTestId("source-label")).toHaveText("ASC");
  await expect(card.getByTestId("syllabus")).toHaveCount(0);
  const toggle = card.getByRole("button", { name: "Show syllabus" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(card.getByTestId("syllabus")).toContainText("Pollaczek-Khinchine");
  await card.getByRole("button", { name: "Hide syllabus" }).click();
  await expect(card.getByTestId("syllabus")).toHaveCount(0);
});

test("grades are never read: no grades card and no Show grades button for any ASC question", async ({ page }) => {
  await page.goto("/");
  await ask(page, "Which are my registered courses?");
  await expect(page.getByTestId("course-card")).toHaveCount(4, { timeout: 15_000 });
  await expect(page.getByRole("button", { name: /grades/i })).toHaveCount(0);
  await expect(page.getByTestId("grade-card")).toHaveCount(0);
});

test("with a cloud model, a question about your own ASC data gets the local-model-only refusal and no cards", async ({ page }) => {
  await page.goto("/?mockCloud=1");
  await ask(page, "What's my timetable tomorrow?");
  await expect(page.getByRole("article")).toContainText(
    "That needs your ASC data, which CampusPilot only shares with the local model. Switch to Local Gemma in Settings.",
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("slot-card")).toHaveCount(0);
  await expect(page.getByTestId("personal-cards")).toHaveCount(0);
  // Public ASC questions still work with a cloud model.
  await ask(page, "When is IE 307 offered?");
  await expect(page.getByTestId("history-card")).toBeVisible({ timeout: 15_000 });
});

test("mail and ASC cards are never written to localStorage; after a reload the chat says so", async ({ page }) => {
  await page.goto("/");
  await ask(page, "What is my fee status?");
  await expect(page.getByTestId("fee-card")).toHaveCount(3, { timeout: 15_000 });
  await page.waitForTimeout(700); // the chat is saved shortly after each change
  const saved = await page.evaluate(() => localStorage.getItem("campuspilot.conversations.v1") ?? "");
  expect(saved).toContain("ASC shows 3 fee items"); // the answer text is saved as before
  expect(saved).not.toContain("Hostel rent"); // ... but no card content
  expect(saved).not.toContain("Rs 3,000");

  await page.reload();
  await page.getByRole("button", { name: /fee status/ }).first().click();
  await expect(page.getByRole("article")).toContainText("aren't kept in this browser");
  await expect(page.getByTestId("fee-card")).toHaveCount(0);
});

test("What's due: Moodle deadlines and mail deadline cards, each with its own source label", async ({ page }) => {
  await page.goto("/?mockConnectors=connected");
  await ask(page, "What's due this week?");
  const deadlines = page.getByRole("region", { name: "Deadlines" });
  await expect(deadlines.getByRole("link", { name: /Open in Moodle/ })).toHaveCount(4, { timeout: 15_000 });
  expect(new Set(await deadlines.getByTestId("source-label").allTextContents())).toEqual(new Set(["Moodle"]));
  const events = page.getByRole("region", { name: "Events from your mail" });
  await expect(events.getByTestId("event-card")).toHaveCount(2);
  expect(new Set(await events.getByTestId("source-label").allTextContents())).toEqual(new Set(["Webmail"]));
  await expect(events.getByTestId("event-card").first()).toContainText("Deadline");
  await expect(page.getByRole("article")).toContainText("2 more found in your mail");
});

test("document sources carry the Official page label", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Code of conduct basics" }).click();
  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByTestId("source-label").first()).toHaveText("Official page", { timeout: 15_000 });
});

test("demo data is labelled once for the whole group of cards", async ({ page }) => {
  await page.goto("/?mockConnectors=demo");
  await ask(page, "Any institute events this week from my mail?");
  await expect(page.getByTestId("personal-cards").getByText("Demo data").first()).toBeVisible({ timeout: 15_000 });
  // Demo events can never be added.
  await expect(page.getByTestId("event-card").first().getByRole("button", { name: "Demo data" })).toBeDisabled();
});

// ---------- Settings -> Connectors ----------

test("Settings lists the three connectors with their status", async ({ page }) => {
  await page.goto("/");
  const dialog = await openSettings(page);
  await expect(dialog.getByRole("heading", { name: "Connectors" })).toBeVisible();
  for (const title of ["IITB Webmail", "ASC", "Google Calendar"]) await expect(dialog.getByRole("heading", { name: title })).toBeVisible();
  await expect(dialog.getByTestId("connector-webmail")).toContainText("Not connected");
  await expect(dialog.getByText("campus network or the IITB VPN")).toBeVisible();
  await dialog.getByRole("button", { name: "Connect IITB Webmail" }).click();
  await expect(dialog.getByText("stored in your Mac's Keychain", { exact: false })).toBeVisible();
  await expect(dialog.getByText("Never sent anywhere else", { exact: false })).toBeVisible();
  // Webmail needs an SSO access token, not the LDAP password, and says where to make one.
  await expect(dialog.getByLabel("LDAP ID")).toHaveAttribute("placeholder", /24b0000/);
  const help = dialog.getByRole("link", { name: /sso\.iitb\.ac\.in/ });
  await expect(help).toHaveAttribute("href", "https://sso.iitb.ac.in");
  await expect(help).toHaveAttribute("target", "_blank");
  await expect(help).toHaveAttribute("rel", "noopener noreferrer");
  await expect(dialog.getByText("It's not your LDAP password", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click(); // folds the form again
  await expect(dialog.getByLabel("LDAP ID")).toHaveCount(0);
});

test("connect IITB Webmail, then disconnect with a confirmation", async ({ page }) => {
  await page.goto("/");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-webmail");
  await expect(card.getByLabel("SSO access token (Emails)")).toHaveCount(0); // the form is folded until Connect is pressed
  await card.getByRole("button", { name: "Connect IITB Webmail" }).click();
  const password = card.getByLabel("SSO access token (Emails)");
  await expect(card.getByLabel("LDAP ID")).toBeFocused(); // the form opens with focus on the first field
  await card.getByLabel("LDAP ID").fill("demo.student");
  await password.fill("fake-password-1");
  await expect(password).toHaveAttribute("type", "password"); // masked
  await card.getByRole("button", { name: "Connect", exact: true }).click();

  await expect(card).toContainText("Connected as demo.student");
  await expect(card.getByLabel("SSO access token (Emails)")).toHaveCount(0); // the form is gone, so is the password
  // Focus moved to the card title, not lost.
  await expect(card.getByRole("heading", { name: "IITB Webmail" })).toBeFocused();

  await card.getByRole("button", { name: "Disconnect IITB Webmail" }).click();
  await expect(card).toContainText("Disconnect IITB Webmail?");
  await card.getByRole("button", { name: "Cancel" }).click();
  await expect(card).toContainText("Connected as demo.student"); // cancel changes nothing
  await card.getByRole("button", { name: "Disconnect IITB Webmail" }).click();
  await card.getByRole("button", { name: "Yes, disconnect" }).click();
  await expect(card).toContainText("Not connected");
});

test("a wrong password shows a friendly error and the form stays", async ({ page }) => {
  await page.goto("/");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-webmail");
  await card.getByRole("button", { name: "Connect IITB Webmail" }).click();
  await card.getByLabel("LDAP ID").fill("demo.student");
  await card.getByLabel("SSO access token (Emails)").fill("bad-password");
  await card.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(card.getByRole("alert")).toContainText("not accepted");
  await expect(card.getByLabel("SSO access token (Emails)")).toHaveValue(""); // cleared as soon as it was sent
});

test("ASC card: new text, LDAP ID and LDAP password, connects straight away with no one-time-code step", async ({ page }) => {
  await page.goto("/");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-asc");
  await expect(card).toContainText("timetable, courses, registration, profile and fee status. Grades are never read.");
  await expect(card).not.toContainText("grades and"); // the old text listed grades as something it shows
  await card.getByRole("button", { name: "Connect ASC" }).click();
  await card.getByLabel("LDAP ID").fill("demo.student");
  await card.getByLabel("LDAP password").fill("fake-password-2");
  await expect(card.getByLabel("LDAP password")).toHaveAttribute("type", "password");
  await card.getByRole("button", { name: "Connect", exact: true }).click();

  await expect(card).toContainText("Connected as demo.student");
  await expect(card).not.toContainText("Needs code");
  await expect(card.getByLabel("One-time code")).toHaveCount(0);
  await expect(card.getByRole("button", { name: "Submit code" })).toHaveCount(0);
  await expect(card.getByRole("heading", { name: "ASC" })).toBeFocused();
  await expect(card).toContainText("Your ASC data is only shared with the local model.");
});

test("ASC login with a wrong password shows a friendly error and no code step", async ({ page }) => {
  await page.goto("/");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-asc");
  await card.getByRole("button", { name: "Connect ASC" }).click();
  await card.getByLabel("LDAP ID").fill("demo.student");
  await card.getByLabel("LDAP password").fill("bad-password");
  await card.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(card.getByRole("alert")).toContainText("not accepted");
  await expect(card.getByLabel("One-time code")).toHaveCount(0);
});

test("Refresh ASC data sends one confirmed POST, shows a busy state, then Updated just now", async ({ page }) => {
  const posts: Request[] = [];
  const twentyMinAgo = new Date(Date.now() - 20 * 60_000).toISOString();
  await fakeApi(page, {
    connectors: { webmail: status("webmail", "not_connected"), asc: status("asc", "connected", { account: "demo.student", refreshed_at: twentyMinAgo }), gcal: status("gcal", "not_connected") },
  });
  await page.route("**/v1/connectors/asc/refresh", async (r) => {
    if (r.request().method() === "POST") {
      posts.push(r.request());
      await new Promise((res) => setTimeout(res, 400)); // long enough to see the busy state
    }
    return json(r, status("asc", "connected", { account: "demo.student", refreshed_at: new Date().toISOString() }));
  });
  await page.goto("/?mockNet=1");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-asc");
  await expect(card.getByTestId("asc-updated")).toHaveText("Updated 20 minutes ago");
  await card.getByRole("button", { name: "Refresh ASC data" }).click();
  await expect(card.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
  await expect(card.getByTestId("asc-updated")).toHaveText("Updated just now");
  await expect(card.getByRole("button", { name: "Refresh ASC data" })).toBeEnabled();

  expect(posts).toHaveLength(1);
  expect(new URL(posts[0].url()).pathname).toBe("/v1/connectors/asc/refresh");
  expect(posts[0].headers()["x-campuspilot-confirm"]).toBe("yes");
});

test("Refresh ASC data: an error shows inline and the button works again", async ({ page }) => {
  await fakeApi(page, {
    connectors: { webmail: status("webmail", "not_connected"), asc: status("asc", "connected", { account: "demo.student" }), gcal: status("gcal", "not_connected") },
  });
  await page.route("**/v1/connectors/asc/refresh", (r) => json(r, { code: "UNREACHABLE", message: "ASC needs the campus network or IITB VPN." }, 503));
  await page.goto("/?mockNet=1");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-asc");
  await expect(card.getByTestId("asc-updated")).toHaveCount(0); // no refreshed_at yet, so no "Updated" text
  await card.getByRole("button", { name: "Refresh ASC data" }).click();
  await expect(card.getByRole("alert")).toContainText("ASC needs the campus network or IITB VPN.");
  await expect(card.getByRole("button", { name: "Refresh ASC data" })).toBeEnabled();
});

test("Refresh ASC data only appears on the ASC card, and only when connected", async ({ page }) => {
  await page.goto("/"); // nothing connected
  let dialog = await openSettings(page);
  await expect(dialog.getByRole("button", { name: "Refresh ASC data" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.goto("/?mockConnectors=connected");
  dialog = await openSettings(page);
  await expect(dialog.getByTestId("connector-asc").getByRole("button", { name: "Refresh ASC data" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Refresh ASC data" })).toHaveCount(1);
  await expect(dialog.getByTestId("connector-asc").getByTestId("asc-updated")).toHaveText("Updated 20 minutes ago");
});

test("Google Calendar connects through the sign-in tab flow and can be disconnected", async ({ page }) => {
  await page.goto("/");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-gcal");
  await card.getByRole("button", { name: "Connect Google Calendar" }).click();
  await expect(card).toContainText("Waiting for Google");
  await expect(card).toContainText("Connected as demo.student@example.com", { timeout: 10_000 });
  await card.getByRole("button", { name: "Disconnect Google Calendar" }).click();
  await card.getByRole("button", { name: "Yes, disconnect" }).click();
  await expect(card).toContainText("Not connected");
});

test("a connector that is turned off says which .env flag to set", async ({ page }) => {
  await page.goto("/?mockConnectors=off");
  const dialog = await openSettings(page);
  await expect(dialog.getByTestId("connector-webmail")).toContainText("Turned off");
  await expect(dialog.getByTestId("connector-webmail")).toContainText("WEBMAIL_ENABLED=true");
  await expect(dialog.getByTestId("connector-asc")).toContainText("ASC_ENABLED=true");
  await expect(dialog.getByTestId("connector-gcal")).toContainText("GCAL_ENABLED=true");
  await expect(dialog.getByLabel("LDAP password")).toHaveCount(0); // no form for a connector that is off
});

test("demo connectors carry a Demo data badge", async ({ page }) => {
  await page.goto("/?mockConnectors=demo");
  const dialog = await openSettings(page);
  await expect(dialog.getByTestId("connector-webmail")).toContainText("Demo data");
  await expect(dialog.getByTestId("connector-webmail")).toContainText("Connected as demo.student");
});

test("login and disconnect requests carry the confirm header and nothing is kept in browser storage", async ({ page }) => {
  const calls: { method: string; url: string; confirm: string | undefined; body: unknown }[] = [];
  let webmail = status("webmail", "not_connected");
  await page.route("**/v1/ping", (r) => json(r, { ok: true }));
  await page.route("**/v1/status", (r) => json(r, LOCAL_STATUS));
  await page.route("**/v1/connectors", (r) =>
    json(r, { webmail, asc: status("asc", "not_connected"), gcal: status("gcal", "not_connected") }),
  );
  await page.route("**/v1/connectors/webmail**", (r) => {
    const req = r.request();
    if (req.method() === "OPTIONS") return json(r, null);
    calls.push({ method: req.method(), url: req.url(), confirm: req.headers()["x-campuspilot-confirm"], body: req.postData() ? req.postDataJSON() : null });
    webmail = req.method() === "POST" ? status("webmail", "connected", { account: "demo.student" }) : status("webmail", "not_connected");
    return json(r, webmail);
  });
  await page.goto("/?mockNet=1");
  const dialog = await openSettings(page);
  const card = dialog.getByTestId("connector-webmail");
  await card.getByRole("button", { name: "Connect IITB Webmail" }).click();
  await card.getByLabel("LDAP ID").fill("demo.student");
  await card.getByLabel("SSO access token (Emails)").fill("fake-password-3");
  await card.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(card).toContainText("Connected as demo.student");
  await card.getByRole("button", { name: "Disconnect IITB Webmail" }).click();
  await card.getByRole("button", { name: "Yes, disconnect" }).click();
  await expect(card).toContainText("Not connected");

  expect(calls.map((c) => `${c.method} ${new URL(c.url).pathname}`)).toEqual(["POST /v1/connectors/webmail/login", "DELETE /v1/connectors/webmail"]);
  expect(calls.every((c) => c.confirm === "yes")).toBe(true);
  expect(calls[0].body).toEqual({ username: "demo.student", password: "fake-password-3" }); // sent once, as the contract says
  // The password is nowhere in this browser afterwards.
  const stored = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }]));
  expect(stored).not.toContain("fake-password-3");
});

// ---------- hosted mode ----------

test("hosted mode: no Connectors section and no connector or calendar requests at all", async ({ page }) => {
  const seen: string[] = [];
  page.on("request", (r) => {
    const p = new URL(r.url()).pathname;
    if (p.startsWith("/v1/connectors") || p.startsWith("/v1/calendar")) seen.push(`${r.method()} ${p}`);
  });
  await page.route("**/v1/ping", (r) => json(r, { ok: true }));
  await page.route("**/v1/status", (r) => json(r, { ...LOCAL_STATUS, deploy_mode: "hosted", connectors: [], mode: "byok", model: "byok" }));
  await page.route("**/v1/connectors**", (r) => json(r, { code: "NOT_AVAILABLE", message: "should never be called" }, 404));
  await page.route("**/v1/calendar/**", (r) => json(r, { code: "NOT_AVAILABLE", message: "should never be called" }, 404));
  await page.addInitScript(() => sessionStorage.setItem("campuspilot.llm.v1", JSON.stringify({ provider: "groq", key: "testkey_abcdefghijklmnopqrstuvwxyz123456" })));
  await page.goto("/?mockNet=1");
  await expect(page.getByTestId("provider-pill")).toBeVisible();
  const dialog = await openSettings(page);
  await expect(dialog.getByRole("heading", { name: "1. Model key" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Connectors" })).toHaveCount(0);
  await expect(dialog.getByText("IITB Webmail")).toHaveCount(0);
  await page.waitForTimeout(500);
  expect(seen).toEqual([]);
});

test("an API without the connector endpoints (404) just hides the section", async ({ page }) => {
  await page.route("**/v1/ping", (r) => json(r, { ok: true }));
  await page.route("**/v1/status", (r) => json(r, LOCAL_STATUS));
  await page.route("**/v1/connectors", (r) => json(r, { code: "NOT_AVAILABLE", message: "nope" }, 404));
  await page.goto("/?mockNet=1");
  const dialog = await openSettings(page);
  await expect(dialog.getByRole("heading", { name: "Model status" })).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Connectors" })).toHaveCount(0);
});

// ---------- phone layout ----------

test("390 px: event cards, timetable and Settings -> Connectors do not overflow sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?mockConnectors=connected");
  const noOverflow = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  await ask(page, "Any institute events this week from my mail?");
  await expect(page.getByTestId("event-card")).toHaveCount(2, { timeout: 15_000 });
  expect(await noOverflow()).toBe(true);
  for (const card of await page.getByTestId("event-card").all()) {
    const box = await card.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  }

  await ask(page, "What's my timetable tomorrow?");
  await expect(page.getByTestId("slot-card")).toHaveCount(3, { timeout: 15_000 });
  expect(await noOverflow()).toBe(true);

  // The new ASC cards: profile, fees, offering history, course details (syllabus open) and the long course list.
  await ask(page, "Show my profile");
  await expect(page.getByTestId("profile-card")).toBeVisible({ timeout: 15_000 });
  expect(await noOverflow()).toBe(true);
  await ask(page, "What is my fee status?");
  await expect(page.getByTestId("fee-card")).toHaveCount(3, { timeout: 15_000 });
  expect(await noOverflow()).toBe(true);
  await ask(page, "When is IE 307 offered?");
  await expect(page.getByTestId("history-card")).toBeVisible({ timeout: 15_000 });
  expect(await noOverflow()).toBe(true);
  await ask(page, "What are the prerequisites of IE 307?");
  await page.getByRole("button", { name: "Show syllabus" }).click();
  await expect(page.getByTestId("syllabus")).toBeVisible({ timeout: 15_000 });
  expect(await noOverflow()).toBe(true);
  await ask(page, "Which IE courses are offered in autumn 2026?");
  await page.getByRole("button", { name: /Show all 14/ }).click();
  await expect(page.getByTestId("course-card")).toHaveCount(14, { timeout: 15_000 });
  expect(await noOverflow()).toBe(true);

  // Settings is reached through the sidebar drawer on a phone.
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  const dialog = await openSettings(page);
  await expect(dialog.getByRole("heading", { name: "Connectors" })).toBeVisible();
  await expect(dialog.getByTestId("connector-asc")).toBeVisible();
  expect(await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
});
