/**
 * The one way the web app talks to the GRIDWISE API (decision 0014).
 *
 * Every call goes through `request`: one timeout, one error model, and a decoder for the
 * response body. A body that does not decode is a failure, never a guess. Nothing here
 * retries on its own: a write that fails is reported, and the person decides.
 */

import { API_BASE_URL, REQUEST_TIMEOUT_MS } from "@/lib/api";

export interface ErrorDetail {
  location: (string | number)[];
  message: string;
  type: string;
}

/** Why a request did not give usable data. Each kind has its own state in the UI. */
export type ApiFailure =
  /** No answer: network error, CORS refusal or timeout. */
  | { kind: "unreachable"; message: string }
  /** The route does not exist: the API runs outside local and test (decisions 0009, 0013). */
  | { kind: "not_available" }
  /** The API has no development tenant configured (503). */
  | { kind: "no_tenant" }
  /** The resource does not exist, or belongs to another tenant: the API cannot tell. */
  | { kind: "not_found"; code: string; message: string }
  /** 409 or 412: the request conflicts with the stored state. */
  | {
      kind: "conflict";
      status: number;
      code: string;
      message: string;
      details: ErrorDetail[];
      /** From the ETag of a 412: the version the grid is at now. */
      currentVersion: number | null;
    }
  /** 400, 422 or 428: the request was refused as it was. */
  | { kind: "invalid"; status: number; code: string; message: string; details: ErrorDetail[] }
  /** 500: logged by the API; only the request id is useful to show. */
  | { kind: "server"; requestId: string | null }
  /** Any other status, or a body that is not what the API documents. */
  | { kind: "unexpected"; status: number | null; message: string }
  /** The caller cancelled the request (for example, the page was left). */
  | { kind: "aborted" };

export type ApiResult<T> =
  | {
      ok: true;
      status: number;
      data: T;
      /** The version from a strong ETag (`"3"`), when the response has one. */
      etag: number | null;
      location: string | null;
      headers: Headers;
    }
  | { ok: false; failure: ApiFailure };

/** Turns an untrusted payload into `T`, or `null` when it is not one. */
export type Decoder<T> = (value: unknown) => T | null;

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** The version the caller read; sent as a strong ETag in If-Match. */
  ifMatch?: number;
  idempotencyKey?: string;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
  baseUrl?: string;
  timeoutMs?: number;
}

const STRONG_VERSION_TAG = /^"([1-9][0-9]{0,9})"$/;

export function versionFromEtag(value: string | null): number | null {
  if (value === null) return null;
  const match = STRONG_VERSION_TAG.exec(value.trim());
  return match?.[1] === undefined ? null : Number(match[1]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

interface ErrorBody {
  code: string;
  message: string;
  requestId: string | null;
  details: ErrorDetail[];
}

function decodeDetail(value: unknown): ErrorDetail | null {
  if (!isRecord(value)) return null;
  const { location, message, type } = value;
  if (
    !Array.isArray(location) ||
    !location.every((part) => typeof part === "string" || typeof part === "number") ||
    typeof message !== "string" ||
    typeof type !== "string"
  ) {
    return null;
  }
  return { location, message, type };
}

/** The API's one error shape: `{"error": {code, message, request_id, details?}}`. */
export function decodeErrorBody(value: unknown): ErrorBody | null {
  if (!isRecord(value) || !isRecord(value.error)) return null;
  const { code, message, request_id: requestId, details } = value.error;
  if (typeof code !== "string" || typeof message !== "string") return null;
  if (requestId !== undefined && requestId !== null && typeof requestId !== "string") return null;
  const decoded = Array.isArray(details) ? details.map(decodeDetail) : [];
  if (decoded.some((item) => item === null)) return null;
  return {
    code,
    message,
    requestId: requestId ?? null,
    details: decoded.filter((item): item is ErrorDetail => item !== null),
  };
}

export function failureFromResponse(
  status: number,
  body: ErrorBody | null,
  etag: string | null,
): ApiFailure {
  if (status === 404 && (body === null || body.code === "not_found")) {
    // FastAPI's own 404: there is no such route here, so these APIs are not deployed.
    return { kind: "not_available" };
  }
  if (status === 503 && body?.code === "development_tenant_not_configured") {
    return { kind: "no_tenant" };
  }
  if (status >= 500) return { kind: "server", requestId: body?.requestId ?? null };
  if (body === null) {
    return { kind: "unexpected", status, message: `Unexpected HTTP ${status}` };
  }
  const { code, message, details } = body;
  if (status === 404) return { kind: "not_found", code, message };
  if (status === 409 || status === 412) {
    return {
      kind: "conflict",
      status,
      code,
      message,
      details,
      currentVersion: status === 412 ? versionFromEtag(etag) : null,
    };
  }
  if (status === 400 || status === 422 || status === 428) {
    return { kind: "invalid", status, code, message, details };
  }
  return { kind: "unexpected", status, message };
}

/** One signal that fires on the caller's abort or on the deadline, whichever comes first. */
function combinedSignal(
  timeoutMs: number,
  external: AbortSignal | undefined,
): { signal: AbortSignal; timedOut: () => boolean; dispose: () => void } {
  const controller = new AbortController();
  let expired = false;
  const timer = setTimeout(() => {
    expired = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  if (external?.aborted) controller.abort();
  external?.addEventListener("abort", onAbort);
  return {
    signal: controller.signal,
    timedOut: () => expired,
    dispose: () => {
      clearTimeout(timer);
      external?.removeEventListener("abort", onAbort);
    },
  };
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === "") return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

export async function request<T>(
  path: string,
  decode: Decoder<T>,
  {
    method = "GET",
    body,
    ifMatch,
    idempotencyKey,
    signal,
    fetchImpl = fetch,
    baseUrl = API_BASE_URL,
    timeoutMs = REQUEST_TIMEOUT_MS,
  }: RequestOptions = {},
): Promise<ApiResult<T>> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (ifMatch !== undefined) headers["If-Match"] = `"${ifMatch}"`;
  if (idempotencyKey !== undefined) headers["Idempotency-Key"] = idempotencyKey;

  const deadline = combinedSignal(timeoutMs, signal);
  try {
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: deadline.signal,
    });
    const payload = await readJson(response);
    if (!response.ok) {
      return {
        ok: false,
        failure: failureFromResponse(
          response.status,
          decodeErrorBody(payload),
          response.headers.get("ETag"),
        ),
      };
    }
    const data = response.status === 204 ? decode(undefined) : decode(payload);
    if (data === null) {
      return {
        ok: false,
        failure: {
          kind: "unexpected",
          status: response.status,
          message: "The API answered with data in an unrecognised shape",
        },
      };
    }
    return {
      ok: true,
      status: response.status,
      data,
      etag: versionFromEtag(response.headers.get("ETag")),
      location: response.headers.get("Location"),
      headers: response.headers,
    };
  } catch {
    if (deadline.timedOut()) {
      const seconds = Math.round(timeoutMs / 100) / 10;
      return {
        ok: false,
        failure: { kind: "unreachable", message: `No response within ${seconds} seconds` },
      };
    }
    if (signal?.aborted) return { ok: false, failure: { kind: "aborted" } };
    return { ok: false, failure: { kind: "unreachable", message: "No response from the API" } };
  } finally {
    deadline.dispose();
  }
}

/** For responses without a body (204). */
export const noContent: Decoder<true> = (value) => (value === undefined ? true : null);
