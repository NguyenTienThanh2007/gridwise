import { describe, expect, it } from "vitest";
import { buildContentSecurityPolicy, buildSecurityHeaders } from "@/lib/security-headers";

const production = { apiUrl: "http://localhost:8020/some/path", development: false };

function directive(policy: string, name: string): string[] {
  const match = policy.split("; ").find((part) => part.startsWith(`${name} `));
  if (match === undefined) throw new Error(`missing directive ${name}`);
  return match.split(" ").slice(1);
}

describe("security headers", () => {
  it("sets every required header", () => {
    const headers = Object.fromEntries(
      buildSecurityHeaders(production).map(({ key, value }) => [key, value]),
    );
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
    expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(headers["X-Frame-Options"]).toBe("DENY");
    expect(headers["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
  });

  it("allows connections to the API origin only, not its path or any wildcard", () => {
    const policy = buildContentSecurityPolicy(production);
    expect(directive(policy, "connect-src")).toEqual(["'self'", "http://localhost:8020"]);
    expect(directive(policy, "default-src")).toEqual(["'self'"]);
    expect(directive(policy, "object-src")).toEqual(["'none'"]);
    expect(policy).not.toContain("*");
  });

  it("never allows eval or WebSockets in production", () => {
    const policy = buildContentSecurityPolicy(production);
    expect(policy).not.toContain("unsafe-eval");
    expect(policy).not.toContain("ws:");
  });

  it("relaxes only what hot reload needs in development", () => {
    const policy = buildContentSecurityPolicy({ ...production, development: true });
    expect(directive(policy, "script-src")).toContain("'unsafe-eval'");
    expect(directive(policy, "connect-src")).toContain("ws:");
    expect(directive(policy, "frame-ancestors")).toEqual(["'none'"]);
  });

  it("rejects a malformed API URL instead of emitting a broken policy", () => {
    expect(() => buildContentSecurityPolicy({ apiUrl: "not a url", development: false })).toThrow();
  });
});
