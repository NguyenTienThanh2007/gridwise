import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import type { ApiFailure } from "@/lib/http/client";
import { API_BASE_URL } from "@/lib/api";

/** The title and explanation of a failure, for one resource ("grid", "grids", ...). */
export function describeFailure(
  failure: ApiFailure,
  resource: string,
): { title: string; detail: string } {
  switch (failure.kind) {
    case "unreachable":
      return {
        title: "The API is unreachable",
        detail: `${failure.message}. Check that the API runs at ${API_BASE_URL} and that this page is opened from an allowed origin (http://localhost:3100 by default).`,
      };
    case "not_available":
      return {
        title: "Not available in this environment",
        detail:
          "The grid and simulation APIs exist only in local and test environments, for the development organisation.",
      };
    case "no_tenant":
      return {
        title: "No development organisation is configured",
        detail:
          "Set GRIDWISE_DEV_ORGANIZATION_ID in .env (local and test only) and restart the API.",
      };
    case "not_found":
      return {
        title: `No such ${resource}`,
        detail: `The ${resource} does not exist, or it belongs to another organisation.`,
      };
    case "conflict":
      return { title: "The request conflicts with the stored data", detail: failure.message };
    case "invalid":
      return { title: "The request was refused", detail: failure.message };
    case "server":
      return {
        title: "The API reported an internal error",
        detail:
          failure.requestId === null
            ? "It has been logged by the API."
            : `It has been logged by the API with request id ${failure.requestId}.`,
      };
    case "unexpected":
      return { title: "Unexpected answer from the API", detail: failure.message };
    case "aborted":
      return { title: "The request was cancelled", detail: "Try again." };
  }
}

export function ErrorState({
  failure,
  resource,
  onRetry,
}: {
  failure: ApiFailure;
  resource: string;
  onRetry?: () => void;
}) {
  const { title, detail } = describeFailure(failure, resource);
  const retryable = failure.kind !== "not_found" && failure.kind !== "not_available";
  return (
    <Notice tone={failure.kind === "not_found" ? "info" : "bad"} title={title} role="alert">
      <p>{detail}</p>
      {onRetry !== undefined && retryable ? (
        <Button className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </Notice>
  );
}
