import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Hide the floating Next.js dev badge; it covered the Settings button.
  devIndicators: false,
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
