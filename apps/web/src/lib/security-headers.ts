/**
 * Response security headers for every page. Kept free of Next.js imports so it can be unit
 * tested and reused by `next.config.ts`.
 */

export interface SecurityHeaderOptions {
  /** Base URL of the GRIDWISE API; its origin is the only cross-origin `connect-src`. */
  apiUrl: string;
  /** `next dev` needs eval and a WebSocket for hot reload; production must not allow them. */
  development: boolean;
}

export interface Header {
  key: string;
  value: string;
}

export function buildContentSecurityPolicy({ apiUrl, development }: SecurityHeaderOptions): string {
  const apiOrigin = new URL(apiUrl).origin;
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    // Next.js bootstraps hydration with inline scripts. Removing 'unsafe-inline' needs a
    // per-request nonce, which forces every page to render dynamically; that is deferred
    // until there is authenticated content to protect (docs/security/safety-boundary.md).
    "script-src": ["'self'", "'unsafe-inline'", ...(development ? ["'unsafe-eval'"] : [])],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'", apiOrigin, ...(development ? ["ws:"] : [])],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(" ")}`)
    .join("; ");
}

export function buildSecurityHeaders(options: SecurityHeaderOptions): Header[] {
  return [
    { key: "Content-Security-Policy", value: buildContentSecurityPolicy(options) },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    // Redundant with frame-ancestors, kept for browsers and scanners that read only this.
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ];
}
