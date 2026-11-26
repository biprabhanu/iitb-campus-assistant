// The Content-Security-Policy, built per request by proxy.ts (a fresh nonce each time).
// Why a nonce: the student's API key lives in this page's storage, so we do not allow inline scripts
// except the ones Next.js and our theme snippet mark with the nonce. 'strict-dynamic' lets those
// trusted scripts load the rest of the app's own chunks.

/** The API origin the browser may talk to (the only cross-origin `connect-src`). */
export function apiOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";
  try {
    return new URL(raw).origin;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

export function buildCsp(nonce: string, dev: boolean): string {
  const directives = [
    "default-src 'self'",
    // 'unsafe-eval' is only for `next dev` (React's debugging tools); never in a production build.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    // React sets a few style="" attributes (animation delays); those need 'unsafe-inline'. No script risk.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${apiOrigin()}${dev ? " ws: wss:" : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ];
  return directives.join("; ");
}
