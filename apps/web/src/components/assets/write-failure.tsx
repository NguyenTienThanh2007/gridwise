import { Button } from "@/components/ui/button";
import { describeFailure } from "@/components/ui/error-state";
import { Notice } from "@/components/ui/notice";
import type { ApiFailure } from "@/lib/http/client";

/**
 * Why a write was not saved. A stale version (412) is explained with the grid's current
 * version and two choices; nothing is ever sent again without the user pressing Save.
 */
export function WriteFailure({
  failure,
  onReloadAndReview,
  onDiscard,
}: {
  failure: ApiFailure;
  onReloadAndReview: (currentVersion: number | null) => void;
  onDiscard: () => void;
}) {
  if (failure.kind === "conflict" && failure.status === 412) {
    return (
      <Notice
        tone="warn"
        title="Not saved: the grid changed since you opened this form"
        role="alert"
      >
        <p>
          {failure.currentVersion === null
            ? "Someone else saved a change first."
            : `It is now version ${failure.currentVersion}.`}{" "}
          Your change was not saved and nothing was overwritten. Reload to see the stored values,
          review your change, and save again.
        </p>
        <div className="mt-2 flex gap-2">
          <Button onClick={() => onReloadAndReview(failure.currentVersion)}>
            Reload and review
          </Button>
          <Button onClick={onDiscard}>Discard my change</Button>
        </div>
      </Notice>
    );
  }
  if (failure.kind === "invalid" && failure.code === "grid_validation_failed") {
    return (
      <Notice tone="bad" title="Not saved: the grid would not be valid" role="alert">
        <p>The engine refused the change. Nothing was stored.</p>
        <ul className="mt-1 list-disc pl-5">
          {failure.details.map((detail) => (
            <li key={`${detail.type}:${detail.location.join(".")}`}>
              {detail.message} <code className="text-xs">{detail.type}</code>
            </li>
          ))}
        </ul>
      </Notice>
    );
  }
  const { title, detail } = describeFailure(failure, "grid");
  return (
    <Notice
      tone="bad"
      title={`Not saved: ${title.charAt(0).toLowerCase()}${title.slice(1)}`}
      role="alert"
    >
      <p>{detail} Your change is kept in the form.</p>
    </Notice>
  );
}
