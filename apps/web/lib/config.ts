// Build-time settings read from NEXT_PUBLIC_* variables (see docs/CONTRACT.md §8).

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");

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
