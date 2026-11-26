// Turning a failed HTTP reply (before any stream starts) into the same error shape as an SSE `error` event.
import type { ErrorEvent, UiErrorCode } from "./types";

const CODES: UiErrorCode[] = [
  "MODEL_OFFLINE", "TIMEOUT", "BAD_REQUEST", "RATE_LIMITED", "INTERNAL", "MODEL_KEY_REQUIRED",
  "PROVIDER_KEY_REJECTED", "PROVIDER_RATE_LIMITED", "PROVIDER_TIMEOUT", "PROVIDER_ERROR", "NOT_AVAILABLE", "NETWORK",
];

function asSeconds(v: unknown): number | null {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && n >= 0 ? Math.min(Math.ceil(n), 3600) : null;
}

/**
 * HTTP 401 / 429 / 4xx / 5xx JSON from POST /v1/chat. The JSON `code` wins; the status is only the fallback.
 * `retryAfterHeader` is the Retry-After header, used when the body has no retry_after_s.
 */
export function httpError(status: number, body: unknown, retryAfterHeader?: string | null): ErrorEvent {
  const j = body && typeof body === "object" ? (body as Record<string, unknown>) : {};
  let code: UiErrorCode =
    typeof j.code === "string" && (CODES as string[]).includes(j.code)
      ? (j.code as UiErrorCode)
      : status === 401
        ? "PROVIDER_KEY_REJECTED"
        : status === 429
          ? "RATE_LIMITED"
          : status >= 500
            ? "INTERNAL"
            : "BAD_REQUEST";
  // A 429 from our own server is RATE_LIMITED even if the body forgot the code.
  if (status === 429 && code === "BAD_REQUEST") code = "RATE_LIMITED";
  return {
    code,
    message: typeof j.message === "string" && j.message ? j.message : "Something went wrong on the server. Please try again.",
    provider: typeof j.provider === "string" ? j.provider : null,
    retry_after_s: asSeconds(j.retry_after_s) ?? asSeconds(retryAfterHeader),
    at: Date.now(),
  };
}
