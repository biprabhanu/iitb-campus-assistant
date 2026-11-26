// Small wrappers for the non-chat endpoints (docs/CONTRACT.md §2).
import { API_BASE, MOCK } from "./config";
import { mockDeleteMoodle, mockSendMoodle, mockStatus } from "./mock-stream";
import type { MoodleTokenRequest, MoodleTokenResponse, StatusResponse } from "./types";

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
