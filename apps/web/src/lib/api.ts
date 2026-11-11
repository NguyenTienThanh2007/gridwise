/** Client for the GRIDWISE API. Payloads are validated: the UI never trusts shapes. */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8020";

/** One deadline for the whole status check, so the dashboard can never wait forever. */
export const REQUEST_TIMEOUT_MS = 8_000;

const DATABASE_STATES = ["ok", "unavailable", "not_migrated", "schema_mismatch"] as const;
export type DatabaseState = (typeof DATABASE_STATES)[number];

export interface Readiness {
  status: "ready" | "not_ready";
  database: DatabaseState;
  schema_revision: string | null;
  expected_schema_revision: string | null;
}

export interface SystemInfo {
  version: string;
  environment: string;
  operating_mode: string;
  notice: string;
}

export type SystemStatus =
  | { kind: "ready"; readiness: Readiness; info: SystemInfo }
  | { kind: "not_ready"; readiness: Readiness }
  | { kind: "unreachable"; reason: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function optionalString(value: unknown): string | null | undefined {
  if (value === null || value === undefined) return null;
  return typeof value === "string" ? value : undefined;
}

export function parseReadiness(value: unknown): Readiness | null {
  if (!isRecord(value)) return null;
  const { status, database } = value;
  if (status !== "ready" && status !== "not_ready") return null;
  const state = DATABASE_STATES.find((candidate) => candidate === database);
  const revision = optionalString(value.schema_revision);
  const expected = optionalString(value.expected_schema_revision);
  if (state === undefined || revision === undefined || expected === undefined) return null;
  return { status, database: state, schema_revision: revision, expected_schema_revision: expected };
}

export function parseSystemInfo(value: unknown): SystemInfo | null {
  if (!isRecord(value)) return null;
  const { version, environment, operating_mode, notice } = value;
  if (
    typeof version !== "string" ||
    typeof environment !== "string" ||
    typeof operating_mode !== "string" ||
    typeof notice !== "string"
  ) {
    return null;
  }
  return { version, environment, operating_mode, notice };
}

function isTimeout(error: unknown): boolean {
  return isRecord(error) && (error.name === "TimeoutError" || error.name === "AbortError");
}

export async function fetchSystemStatus(
  fetchImpl: typeof fetch = fetch,
  baseUrl: string = API_BASE_URL,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<SystemStatus> {
  const request: RequestInit = { cache: "no-store", signal: AbortSignal.timeout(timeoutMs) };
  try {
    const readyResponse = await fetchImpl(`${baseUrl}/health/ready`, request);
    // 503 is a valid answer with a body: the API is up but cannot serve yet.
    if (!readyResponse.ok && readyResponse.status !== 503) {
      return { kind: "unreachable", reason: `Unexpected HTTP ${readyResponse.status}` };
    }
    const readiness = parseReadiness(await readyResponse.json());
    if (readiness === null) return { kind: "unreachable", reason: "Unrecognised health payload" };
    if (readiness.status !== "ready") return { kind: "not_ready", readiness };

    const infoResponse = await fetchImpl(`${baseUrl}/api/v1/system/info`, request);
    const info = infoResponse.ok ? parseSystemInfo(await infoResponse.json()) : null;
    if (info === null) return { kind: "unreachable", reason: "Unrecognised system payload" };
    return { kind: "ready", readiness, info };
  } catch (error) {
    if (isTimeout(error)) {
      const seconds = Math.round(timeoutMs / 100) / 10;
      return { kind: "unreachable", reason: `No response within ${seconds} seconds` };
    }
    return { kind: "unreachable", reason: "No response from the API" };
  }
}
