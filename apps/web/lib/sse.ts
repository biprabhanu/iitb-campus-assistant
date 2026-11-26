// POST /v1/chat and turn the text/event-stream reply into typed events.
import { API_BASE, MOCK } from "./config";
import { mockChatStream } from "./mock-stream";
import type { ChatRequest, SSEEvent } from "./types";

const KNOWN = new Set(["status", "tool", "sources", "token", "done", "error"]);

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
export async function* streamChat(req: ChatRequest, signal: AbortSignal): AsyncGenerator<SSEEvent> {
  if (MOCK) {
    yield* mockChatStream(req, signal);
    return;
  }

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(req),
      signal,
    });
  } catch (err) {
    if (signal.aborted) return;
    yield {
      event: "error",
      data: {
        code: "NETWORK",
        message: `Can't reach the CampusPilot server at ${API_BASE}. Make sure the API is running, then try again.`,
      },
    };
    void err;
    return;
  }

  if (!res.ok || !res.body) {
    let message = "Something went wrong on the server. Please try again.";
    let code: "BAD_REQUEST" | "RATE_LIMITED" | "INTERNAL" = res.status === 429 ? "RATE_LIMITED" : res.status < 500 ? "BAD_REQUEST" : "INTERNAL";
    try {
      const j = await res.json();
      if (typeof j?.message === "string") message = j.message;
      if (j?.code === "RATE_LIMITED") code = "RATE_LIMITED";
    } catch {
      /* body was not JSON; keep the default message */
    }
    yield { event: "error", data: { code, message } };
    return;
  }

  try {
    yield* parseSSE(res.body);
  } catch (err) {
    if (signal.aborted) return;
    void err;
    yield { event: "error", data: { code: "NETWORK", message: "The connection dropped while answering. Please try again." } };
  }
}
