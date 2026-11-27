// Build-time settings read from NEXT_PUBLIC_* variables (see docs/CONTRACT.md §8).

// NEXT_PUBLIC_API_URL is the documented name; NEXT_PUBLIC_API_BASE is the older one (docs/CONTRACT.md §10.7).
export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

/** true when the API is on this computer. Then "unreachable" means "not started", not "asleep". */
export const API_IS_LOOPBACK = (() => {
  try {
    const h = new URL(API_BASE).hostname;
    return h === "127.0.0.1" || h === "localhost" || h === "[::1]";
  } catch {
    return false;
  }
})();

/** true = the UI never calls the API; lib/mock-stream.ts replays canned events. */
export const MOCK = process.env.NEXT_PUBLIC_MOCK === "true";

/** Mock-only switches. They can also be set with URL params, e.g. /?mockOffline=1 */
function flag(name: string, envValue: string | undefined): boolean {
  if (envValue === "true" || envValue === "1") return true;
  if (typeof window === "undefined") return false;
  try {
    return new URLSearchParams(window.location.search).get(name) === "1";
  } catch {
    return false;
  }
}

export const mockOffline = () => flag("mockOffline", process.env.NEXT_PUBLIC_MOCK_OFFLINE);
/** Simulates a cold model: the first token takes ~5 s. */
export const mockWake = () => flag("mockWake", process.env.NEXT_PUBLIC_MOCK_WAKE);

/**
 * Mock-only, for screenshots: freeze the stream part-way.
 *   ?mockHold=tool  stays on the first step (shimmer + skeleton)
 *   ?mockHold=text  stops after a few words (blinking caret)
 */
export function mockHold(): "tool" | "text" | null {
  if (typeof window === "undefined") return null;
  try {
    const v = new URLSearchParams(window.location.search).get("mockHold");
    return v === "tool" || v === "text" ? v : null;
  } catch {
    return null;
  }
}

/** Mock-only: pretend the API runs in hosted (bring-your-own-key) mode. ?mockHosted=1 */
export const mockHosted = () => flag("mockHosted", process.env.NEXT_PUBLIC_MOCK_HOSTED);

/**
 * Mock-only: pretend the chat model is a cloud model (Groq and the like) instead of local Gemma.
 * ?mockCloud=1: a question about the student's own ASC data (timetable, courses, registration,
 * fees, profile) is then refused with the contract text, as the real API does (CONTRACT 11.8).
 * Public ASC questions (offered courses, offering history, course details) still work.
 */
export const mockCloud = () => flag("mockCloud", process.env.NEXT_PUBLIC_MOCK_CLOUD);

/**
 * Mock-only, for tests: ?mockNet=1 makes the status, ping and connector calls use the real `fetch`
 * (chat stays mocked). Playwright then answers them with `page.route`, so a test can see exactly
 * which requests (and headers) the UI sends.
 */
export const mockNet = () => flag("mockNet", process.env.NEXT_PUBLIC_MOCK_NET);

/**
 * Mock-only: the starting state of the three v2 connectors in Settings.
 *   (default) / ?mockConnectors=none   enabled, nothing connected yet
 *   ?mockConnectors=connected          all three connected
 *   ?mockConnectors=off                all three turned off in .env
 *   ?mockConnectors=demo               connected, with fixture data (demo badge)
 */
export type MockConnectors = "none" | "connected" | "off" | "demo";
export function mockConnectors(): MockConnectors {
  let v: string | null = process.env.NEXT_PUBLIC_MOCK_CONNECTORS ?? null;
  if (typeof window !== "undefined") {
    try {
      v = new URLSearchParams(window.location.search).get("mockConnectors") ?? v;
    } catch {
      /* ignore */
    }
  }
  return v === "connected" || v === "off" || v === "demo" ? v : "none";
}

/**
 * Mock-only: pretend the server is asleep at start-up.
 *   ?mockCold=1     asleep for about a minute (shows "Waking the server")
 *   ?mockCold=fail  never wakes; the retry budget shrinks to ~5 s so the failure card shows quickly
 */
export function mockCold(): "wake" | "fail" | null {
  let v: string | null = process.env.NEXT_PUBLIC_MOCK_COLD ?? null;
  if (typeof window !== "undefined") {
    try {
      v = new URLSearchParams(window.location.search).get("mockCold") ?? v;
    } catch {
      /* ignore */
    }
  }
  return v === "fail" ? "fail" : v === "1" || v === "true" ? "wake" : null;
}

/**
 * Mock-only: make every chat request fail with this code (e.g. ?mockError=PROVIDER_RATE_LIMITED).
 * Only codes from the contract are accepted.
 */
export function mockError(): string | null {
  const allowed = [
    "MODEL_OFFLINE", "TIMEOUT", "BAD_REQUEST", "RATE_LIMITED", "INTERNAL", "MODEL_KEY_REQUIRED",
    "PROVIDER_KEY_REJECTED", "PROVIDER_RATE_LIMITED", "PROVIDER_TIMEOUT", "PROVIDER_ERROR", "NOT_AVAILABLE",
  ];
  const fromEnv = process.env.NEXT_PUBLIC_MOCK_ERROR;
  let v: string | null = fromEnv ?? null;
  if (typeof window !== "undefined") {
    try {
      v = new URLSearchParams(window.location.search).get("mockError") ?? v;
    } catch {
      /* ignore */
    }
  }
  return v && allowed.includes(v) ? v : null;
}
