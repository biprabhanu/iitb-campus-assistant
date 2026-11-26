// POST /v1/chat and turn the text/event-stream reply into typed events.
import { API_BASE, MOCK } from "./config";
import { authHeaders, type LlmCreds, type MoodleCreds } from "./credentials";
import { httpError } from "./errors";
import { mockChatStream } from "./mock-stream";
import type { ChatRequest, SSEEvent } from "./types";

/** What a hosted request carries: the student's own key and (optionally) Moodle credentials. */
export interface RequestAuth {
  llm: LlmCreds | null;
  moodle: MoodleCreds | null;
}

const KNOWN = new Set(["status", "tool", "sources", "cards", "token", "done", "error"]);

/**
 * Parse a Server-Sent Events byte stream. Safe when a chunk ends in the middle of
 * a line, an event or even a multi-byte character: we only act on complete
 * events (those ended by a blank line) and keep the rest in `buffer`.
 */
export async function* parseSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<SSEEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const boundary = /\r?\n\r?\n/;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let match: RegExpExecArray | null;
      while ((match = boundary.exec(buffer))) {
        const block = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const parsed = parseBlock(block);
        if (parsed) yield parsed;
      }
    }
    // Stream ended: flush a last event that had no trailing blank line.
    buffer += decoder.decode();
    const last = parseBlock(buffer);
    if (last) yield last;
  } finally {
    reader.releaseLock();
  }
}

function parseBlock(block: string): SSEEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let val = colon === -1 ? "" : line.slice(colon + 1);
    if (val.startsWith(" ")) val = val.slice(1);
    if (field === "event") event = val;
    else if (field === "data") dataLines.push(val);
  }
  if (!KNOWN.has(event) || dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) } as SSEEvent;
  } catch {
    return null; // ignore a malformed event rather than crash the chat
  }
}

/**
 * Send one chat turn and yield the events. Aborting `signal` (the Stop button)
 * ends the stream quietly.
 */
export async function* streamChat(req: ChatRequest, signal: AbortSignal, auth?: RequestAuth): AsyncGenerator<SSEEvent> {
  if (MOCK) {
    yield* mockChatStream(req, signal, auth);
    return;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...(auth ? authHeaders(auth.llm, auth.moodle) : {}),
      },
      body: JSON.stringify(req),
      signal,
    });
  } catch (err) {
    if (signal.aborted) return;
    yield {
      event: "error",
      data: {
        code: "NETWORK",
        at: Date.now(),
        message: auth
          ? "Can't reach the CampusPilot server. It may still be waking up, so wait a few seconds and try again."
          : `Can't reach the CampusPilot server at ${API_BASE}. Make sure the API is running, then try again.`,
      },
    };
    void err;
    return;
  }

  if (!res.ok || !res.body) {
    // HTTP 401 / 429 JSON arrives before the stream and maps to the same banners as an SSE error.
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* body was not JSON; the status decides */
    }
    yield { event: "error", data: httpError(res.status, body, res.headers.get("retry-after")) };
    return;
  }

  try {
    yield* parseSSE(res.body);
  } catch (err) {
    if (signal.aborted) return;
    void err;
    yield { event: "error", data: { code: "NETWORK", message: "The connection dropped while answering. Please try again.", at: Date.now() } };
  }
}
