import type { NextConfig } from "next";

// Security headers for every response. The Content-Security-Policy (which needs a fresh nonce for each
// request) is added by proxy.ts; see lib/csp.ts for what it allows.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "X-Frame-Options", value: "DENY" }, // older browsers; CSP frame-ancestors covers the rest
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

const nextConfig: NextConfig = {
  // Hide the floating Next.js dev badge; it covered the Settings button.
  devIndicators: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
