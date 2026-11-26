// Small wrappers for the non-chat endpoints (docs/CONTRACT.md §2).
import { API_BASE, MOCK } from "./config";
import { authHeaders, type LlmCreds, type MoodleCreds } from "./credentials";
import { mockCheckLlm, mockCheckMoodle, mockDeleteMoodle, mockPing, mockSendMoodle, mockStatus } from "./mock-stream";
import type { LLMCheckResponse, MoodleTokenRequest, MoodleTokenResponse, StatusResponse } from "./types";

/**
 * Does the server answer GET /v1/ping within `timeoutMs`? Never throws.
 * Not /health: browser ad and tracker blockers block cross-site URLs ending in /health.
 */
export async function pingHealth(timeoutMs: number, signal?: AbortSignal): Promise<boolean> {
  if (MOCK) return mockPing(signal);
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
  if (MOCK) return mockStatus();
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

/** POST /v1/moodle/check: verifies the Moodle token or iCal link, stores nothing. Never throws. */
export async function checkMoodle(creds: MoodleCreds): Promise<MoodleTokenResponse> {
  if (MOCK) return mockCheckMoodle(creds);
  const r = await postWithHeaders("/v1/moodle/check", authHeaders(null, creds));
  if (!r) return { ok: false, mode: "none", message: "Can't reach the CampusPilot server. Wait a few seconds and test again." };
  const j = r.json && typeof r.json === "object" ? (r.json as Partial<MoodleTokenResponse>) : {};
  if (typeof j.ok === "boolean") return { mode: "none", message: "", ...j } as MoodleTokenResponse;
  return { ok: false, mode: "none", message: typeof j.message === "string" ? j.message : "The Moodle check failed." };
}
