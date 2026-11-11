import { readFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";
import type { NextConfig } from "next";
import { buildSecurityHeaders } from "./src/lib/security-headers";

/**
 * The repository has one `.env` for every service, and it holds database credentials.
 * The web app must not see them: this reads the file without touching `process.env` and
 * takes the single public value it needs. Nothing else from the file reaches Next.js.
 */
function readPublicApiUrl(): string | undefined {
  try {
    const file = readFileSync(path.join(import.meta.dirname, "../../.env"), "utf8");
    return parseEnv(file).NEXT_PUBLIC_API_URL;
  } catch {
    return undefined; // no .env (CI, containers): the real environment or the default applies
  }
}

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? readPublicApiUrl() ?? "http://localhost:8020";

const nextConfig: NextConfig = {
  // The container image sets NEXT_OUTPUT=standalone; `next start` needs the default.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  outputFileTracingRoot: path.join(import.meta.dirname, "../.."),
  poweredByHeader: false,
  reactStrictMode: true,
  env: { NEXT_PUBLIC_API_URL: apiUrl },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: buildSecurityHeaders({
          apiUrl,
          development: process.env.NODE_ENV === "development",
        }),
      },
    ];
  },
};

export default nextConfig;
