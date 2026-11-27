// Small wrappers for the non-chat endpoints (docs/CONTRACT.md §2 and §11).
import { API_BASE, MOCK, mockNet } from "./config";
import { authHeaders, type LlmCreds, type MoodleCreds } from "./credentials";
import { mockAddEvent, mockGcalConnect, mockGetConnectors, mockLogin, mockLogout, mockRefreshAsc } from "./mock-connectors";
import { mockCheckLlm, mockCheckMoodle, mockDeleteMoodle, mockPing, mockSendMoodle, mockStatus } from "./mock-stream";
import type {
  CalendarEventRequest,
  CalendarEventResult,
  ConnectorLoginRequest,
  ConnectorName,
  ConnectorsResponse,
  ConnectorStatus,
  GcalConnectStart,
  LLMCheckResponse,
  MoodleTokenRequest,
  MoodleTokenResponse,
  StatusResponse,
  UiErrorCode,
} from "./types";

/** In mock mode the built-in fakes answer, unless ?mockNet=1 asks for the real `fetch` (tests use it). */
const inMockMode = () => MOCK && !mockNet();

/**
 * Does the server answer GET /v1/ping within `timeoutMs`? Never throws.
 * Not /health: browser ad and tracker blockers block cross-site URLs ending in /health.
 */
export async function pingHealth(timeoutMs: number, signal?: AbortSignal): Promise<boolean> {
  if (inMockMode()) return mockPing(signal);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  const onAbort = () => ctl.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const res = await fetch(`${API_BASE}/v1/ping`, { signal: ctl.signal, cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

export async function getStatus(signal?: AbortSignal): Promise<StatusResponse> {
  if (inMockMode()) return mockStatus();
  const res = await fetch(`${API_BASE}/v1/status`, { signal, cache: "no-store" });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

/** Sends the token once. The caller must clear its input afterwards; we never store it. */
export async function sendMoodleCredentials(body: MoodleTokenRequest): Promise<MoodleTokenResponse> {
  if (MOCK) return mockSendMoodle(body);
  const res = await fetch(`${API_BASE}/v1/moodle/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readTokenResponse(res);
}

export async function deleteMoodleCredentials(): Promise<MoodleTokenResponse> {
  if (MOCK) return mockDeleteMoodle();
  const res = await fetch(`${API_BASE}/v1/moodle/token`, { method: "DELETE" });
  return readTokenResponse(res);
}

async function readTokenResponse(res: Response): Promise<MoodleTokenResponse> {
  try {
    const j = await res.json();
    if (typeof j?.ok === "boolean") return j as MoodleTokenResponse;
    return { ok: false, mode: "none", message: typeof j?.message === "string" ? j.message : "Request failed." };
  } catch {
    return { ok: false, mode: "none", message: "The server sent an unexpected reply." };
  }
}

async function postWithHeaders(path: string, headers: Record<string, string>): Promise<{ status: number; json: unknown } | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { method: "POST", headers, cache: "no-store" });
    let json: unknown = null;
    try {
      json = await res.json();
    } catch {
      /* not JSON */
    }
    return { status: res.status, json };
  } catch {
    return null; // network failure
  }
}

/** POST /v1/llm/check with the student's key: one tiny model call. Never throws. */
export async function checkLlm(creds: LlmCreds): Promise<LLMCheckResponse> {
  const fail = (message: string, code: LLMCheckResponse["code"] = "PROVIDER_ERROR"): LLMCheckResponse => ({
    ok: false,
    provider: creds.provider,
    model: creds.model ?? "",
    code,
    message,
  });
  if (MOCK) return mockCheckLlm(creds);
  const r = await postWithHeaders("/v1/llm/check", authHeaders(creds, null));
  if (!r) return fail("Can't reach the CampusPilot server. If it was asleep, wait a few seconds and test again.", "INTERNAL");
  const j = r.json && typeof r.json === "object" ? (r.json as Partial<LLMCheckResponse>) : {};
  if (r.status === 200 && j.ok === true) return { ok: true, provider: j.provider ?? creds.provider, model: j.model ?? "" };
  return {
    ok: false,
    provider: j.provider ?? creds.provider,
    model: j.model ?? "",
    code: j.code ?? (r.status === 401 ? "PROVIDER_KEY_REJECTED" : r.status === 429 ? "RATE_LIMITED" : "PROVIDER_ERROR"),
    message: typeof j.message === "string" && j.message ? j.message : "The key check failed. Please try again.",
    retry_after_s: typeof j.retry_after_s === "number" ? j.retry_after_s : null,
  };
}

/** POST /v1/moodle/check: verifies the Moodle calendar link (or token), stores nothing. Never throws. */
export async function checkMoodle(creds: MoodleCreds): Promise<MoodleTokenResponse> {
  if (MOCK) return mockCheckMoodle(creds);
  const r = await postWithHeaders("/v1/moodle/check", authHeaders(null, creds));
  if (!r) return { ok: false, mode: "none", message: "Can't reach the CampusPilot server. Wait a few seconds and test again." };
  const j = r.json && typeof r.json === "object" ? (r.json as Partial<MoodleTokenResponse>) : {};
  if (typeof j.ok === "boolean") return { mode: "none", message: "", ...j } as MoodleTokenResponse;
  return { ok: false, mode: "none", message: typeof j.message === "string" ? j.message : "The Moodle check failed." };
}

// ---------- v2 connectors (local mode only, docs/CONTRACT.md §11.5) ----------

/** What a connector call gives back: the data, or a friendly, secret-free message. Never throws. */
export type ApiResult<T> = { ok: true; data: T } | { ok: false; code: UiErrorCode; message: string; status: number };

/**
 * The server refuses every POST / DELETE on these endpoints without this header. A custom header
 * makes the browser send a CORS preflight first, so another website cannot trigger them.
 */
const CONFIRM = { "X-CampusPilot-Confirm": "yes" } as const;

const NETWORK_MESSAGE = "Can't reach the CampusPilot server. Make sure the API is running on this computer.";

/** One JSON call to a connector endpoint. The body (a password or code) is sent and then forgotten here. */
async function connectorCall<T>(method: "GET" | "POST" | "DELETE", path: string, body?: unknown): Promise<ApiResult<T>> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      cache: "no-store",
      headers: {
        ...(method === "GET" ? {} : CONFIRM),
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, code: "NETWORK", message: NETWORK_MESSAGE, status: 0 };
  }
  let json: unknown = null;
  try {
    json = await res.json();
  } catch {
    /* not JSON: the status decides */
  }
  if (res.ok && json && typeof json === "object") return { ok: true, data: json as T };
  const j = json && typeof json === "object" ? (json as Record<string, unknown>) : {};
  return {
    ok: false,
    status: res.status,
    code: typeof j.code === "string" ? (j.code as UiErrorCode) : res.status >= 500 ? "INTERNAL" : "BAD_REQUEST",
    message: typeof j.message === "string" && j.message ? j.message : "Something went wrong on the server. Please try again.",
  };
}

/** GET /v1/connectors: the state of all three connectors. */
export async function getConnectors(): Promise<ApiResult<ConnectorsResponse>> {
  if (inMockMode()) return mockGetConnectors();
  return connectorCall<ConnectorsResponse>("GET", "/v1/connectors");
}

/** POST /v1/connectors/webmail/login. The password is sent once and not kept by the caller. */
export async function webmailLogin(req: ConnectorLoginRequest): Promise<ApiResult<ConnectorStatus>> {
  if (inMockMode()) return mockLogin("webmail", req);
  return connectorCall<ConnectorStatus>("POST", "/v1/connectors/webmail/login", req);
}

export async function webmailLogout(): Promise<ApiResult<ConnectorStatus>> {
  if (inMockMode()) return mockLogout("webmail");
  return connectorCall<ConnectorStatus>("DELETE", "/v1/connectors/webmail");
}

/** POST /v1/connectors/asc/login: the LDAP id and password. ASC has no one-time code. */
export async function ascLogin(req: ConnectorLoginRequest): Promise<ApiResult<ConnectorStatus>> {
  if (inMockMode()) return mockLogin("asc", req);
  return connectorCall<ConnectorStatus>("POST", "/v1/connectors/asc/login", req);
}

/**
 * POST /v1/connectors/asc/refresh: read the personal ASC pages again now (timetable, courses,
 * registration, profile, fees). Answers the ASC ConnectorStatus with a new `refreshed_at`.
 * The confirm header is added like on every other POST (CONFIRM).
 */
export async function refreshAsc(): Promise<ApiResult<ConnectorStatus>> {
  if (inMockMode()) return mockRefreshAsc();
  return connectorCall<ConnectorStatus>("POST", "/v1/connectors/asc/refresh");
}

export async function ascLogout(): Promise<ApiResult<ConnectorStatus>> {
  if (inMockMode()) return mockLogout("asc");
  return connectorCall<ConnectorStatus>("DELETE", "/v1/connectors/asc");
}

export async function gcalDisconnect(): Promise<ApiResult<ConnectorStatus>> {
  if (inMockMode()) return mockLogout("gcal");
  return connectorCall<ConnectorStatus>("DELETE", "/v1/connectors/gcal");
}

const GCAL_POLL_MS = 2_000;
const GCAL_TIMEOUT_MS = 3 * 60_000;

/**
 * Connect Google Calendar: ask the API for Google's sign-in address, open it in a new tab, then poll
 * GET /v1/connectors until the API reports Google as connected (Google redirects the other tab to
 * the API, which stores the token). Resolves with the final status, or an error if it takes too
 * long or `signal` is aborted (the Cancel button). `onOpened` says whether the browser allowed the
 * new tab, so the UI can offer a plain link when a pop-up blocker got in the way.
 */
export async function gcalConnect(opts: { signal?: AbortSignal; onOpened?: (authUrl: string, blocked: boolean) => void } = {}): Promise<ApiResult<ConnectorStatus>> {
  const start = inMockMode() ? await mockGcalConnect() : await connectorCall<GcalConnectStart>("POST", "/v1/connectors/gcal/connect");
  if (!start.ok) return start;

  const authUrl = start.data.auth_url;
  // Only ever open a web address (never a javascript: or data: one, even if the server said so).
  const safe = /^https:\/\//i.test(authUrl);
  let blocked = !safe;
  if (safe && !inMockMode()) blocked = window.open(authUrl, "_blank", "noopener,noreferrer") === null;
  opts.onOpened?.(authUrl, blocked);

  const t0 = Date.now();
  while (Date.now() - t0 < GCAL_TIMEOUT_MS) {
    await new Promise<void>((resolve) => {
      const t = setTimeout(resolve, inMockMode() ? 600 : GCAL_POLL_MS);
      opts.signal?.addEventListener("abort", () => (clearTimeout(t), resolve()), { once: true });
    });
    if (opts.signal?.aborted) return { ok: false, code: "NOT_CONNECTED", message: "Cancelled.", status: 0 };
    const res = await getConnectors();
    if (res.ok && res.data.gcal.state === "connected") return { ok: true, data: res.data.gcal };
  }
  return { ok: false, code: "TIMEOUT", message: "Google Calendar didn't finish connecting. Try again and approve access in the Google tab.", status: 0 };
}

/** POST /v1/calendar/events: the one write in the app. One click on "Add" calls this once. */
export async function addCalendarEvent(req: CalendarEventRequest): Promise<ApiResult<CalendarEventResult>> {
  if (inMockMode()) return mockAddEvent(req);
  return connectorCall<CalendarEventResult>("POST", "/v1/calendar/events", req);
}

/** Which flag turns a connector on in .env (shown in the "Turned off" note). */
export const CONNECTOR_FLAGS: Record<ConnectorName, string> = { webmail: "WEBMAIL_ENABLED", asc: "ASC_ENABLED", gcal: "GCAL_ENABLED" };
