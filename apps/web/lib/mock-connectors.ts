// Built-in fake for the v2 connector endpoints (used with NEXT_PUBLIC_MOCK=true, see lib/api.ts).
// State lives in this module's memory only, so a page reload starts again from ?mockConnectors=...
// Nothing here is a real account: logins "work" unless the password contains "bad", and the
// ASC one-time code "000000" is rejected (so both error paths can be tried by hand).
import { mockConnectors } from "./config";
import type { ApiResult } from "./api";
import type {
  CalendarEventRequest,
  CalendarEventResult,
  ConnectorLoginRequest,
  ConnectorName,
  ConnectorOtpRequest,
  ConnectorsResponse,
  ConnectorStatus,
  GcalConnectStart,
} from "./types";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const FLAGS: Record<ConnectorName, string> = { webmail: "WEBMAIL_ENABLED", asc: "ASC_ENABLED", gcal: "GCAL_ENABLED" };

let state: ConnectorsResponse | null = null;
let gcalPendingSince = 0; // when the fake Google tab was "opened"; it approves itself after ~1.5 s
const addedEvents = new Set<string>();

function initial(): ConnectorsResponse {
  const mode = mockConnectors();
  const mk = (name: ConnectorName, account: string): ConnectorStatus => {
    if (mode === "off") return { name, enabled: false, state: "disabled", message: `Off. Set ${FLAGS[name]}=true in .env and restart the API.` };
    if (mode === "connected" || mode === "demo") return { name, enabled: true, state: "connected", account, demo: mode === "demo" };
    return { name, enabled: true, state: "not_connected" };
  };
  return { webmail: mk("webmail", "demo.student"), asc: mk("asc", "demo.student"), gcal: mk("gcal", "demo.student@example.com") };
}

function current(): ConnectorsResponse {
  if (!state) state = initial();
  // The fake Google consent finishes by itself, like a student approving in the other tab.
  if (gcalPendingSince && Date.now() - gcalPendingSince > 1500) {
    state = { ...state, gcal: { name: "gcal", enabled: true, state: "connected", account: "demo.student@example.com" } };
    gcalPendingSince = 0;
  }
  return state;
}

function set(name: ConnectorName, status: ConnectorStatus): ConnectorStatus {
  state = { ...current(), [name]: status };
  return status;
}

const fail = (code: "AUTH_FAILED" | "NOT_AVAILABLE", message: string, status = 401): ApiResult<never> => ({ ok: false, code, message, status });

export async function mockGetConnectors(): Promise<ApiResult<ConnectorsResponse>> {
  await sleep(150);
  return { ok: true, data: current() };
}

export async function mockLogin(name: "webmail" | "asc", req: ConnectorLoginRequest): Promise<ApiResult<ConnectorStatus>> {
  await sleep(600);
  if (current()[name].state === "disabled") return fail("NOT_AVAILABLE", `Turn this on with ${FLAGS[name]}=true in .env.`, 404);
  if (/bad/i.test(req.password)) {
    return fail("AUTH_FAILED", name === "webmail" ? "That LDAP ID or SSO access token was not accepted. Check the token (not your LDAP password) and try again." : "That username or password was not accepted. Check it and try again.");
  }
  if (name === "asc") {
    return { ok: true, data: set(name, { name, enabled: true, state: "needs_otp", account: req.username, challenge_id: "mock-challenge", message: "Enter the one-time code ASC just sent you." }) };
  }
  return { ok: true, data: set(name, { name, enabled: true, state: "connected", account: req.username }) };
}

export async function mockOtp(req: ConnectorOtpRequest): Promise<ApiResult<ConnectorStatus>> {
  await sleep(500);
  if (req.code === "000000") return fail("AUTH_FAILED", "That code didn't work. Check it and try again.");
  return { ok: true, data: set("asc", { name: "asc", enabled: true, state: "connected", account: current().asc.account ?? "demo.student" }) };
}

export async function mockLogout(name: ConnectorName): Promise<ApiResult<ConnectorStatus>> {
  await sleep(300);
  if (name === "gcal") gcalPendingSince = 0;
  return { ok: true, data: set(name, { name, enabled: true, state: "not_connected" }) };
}

export async function mockGcalConnect(): Promise<ApiResult<GcalConnectStart>> {
  await sleep(300);
  gcalPendingSince = Date.now();
  return { ok: true, data: { auth_url: "https://accounts.google.com/o/oauth2/v2/auth?mock=1" } };
}

/** One click = one event; a second click on the same event says "already in your calendar". */
export async function mockAddEvent(req: CalendarEventRequest): Promise<ApiResult<CalendarEventResult>> {
  await sleep(700);
  const link = `https://calendar.google.com/calendar/event?eid=mock-${req.event_id}`;
  if (addedEvents.has(req.event_id)) {
    return { ok: true, data: { ok: true, status: "already_exists", google_event_id: `mock-${req.event_id}`, html_link: link, message: "Already in your calendar." } };
  }
  addedEvents.add(req.event_id);
  return { ok: true, data: { ok: true, status: "created", google_event_id: `mock-${req.event_id}`, html_link: link, message: "Added to your calendar." } };
}
