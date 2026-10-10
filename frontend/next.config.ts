import type { NextConfig } from "next";

// Where the FastAPI backend lives, as seen from the Next.js server
// (http://backend:8000 inside docker compose). The browser never talks to it
// directly: it calls same-origin /api/* and Next.js proxies the request, so the
// backend needs no public port and no CORS.
// NOTE: rewrites are resolved at `next build` (baked into the build output), so in
// Docker pass BACKEND_URL as a build arg. Server Components read it at runtime.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
