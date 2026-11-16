import { Chip, type ChipTone } from "@/components/ui/chip";
import type { Job } from "@/lib/resources/simulations";

/** One status map for the whole app (decision 0015): the words say the state. */
const TONES: Record<Job["status"], ChipTone> = {
  queued: "neutral",
  running: "accent",
  completed: "ok",
  failed: "bad",
  cancelled: "neutral",
};

const LABELS = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
} as const;

/** The job's status in words (never colour alone), with the outcome of a completed job. */
export function statusLabel(job: Pick<Job, "status" | "outcome">): string {
  if (job.status !== "completed") return LABELS[job.status];
  return job.outcome === "not_converged" ? "Completed, did not converge" : "Completed, converged";
}

export function JobStatusBadge({ job }: { job: Pick<Job, "status" | "outcome"> }) {
  const tone: ChipTone =
    job.status === "completed" && job.outcome === "not_converged" ? "warn" : TONES[job.status];
  return <Chip tone={tone}>{statusLabel(job)}</Chip>;
}

/** What the status means for the person waiting. */
export function statusExplanation(job: Job): string {
  switch (job.status) {
    case "queued":
      return "Waiting for a worker to pick it up. A queued job can still be cancelled.";
    case "running":
      return `A worker is solving it (attempt ${job.attempt} of ${job.maxAttempts}). A running job cannot be cancelled.`;
    case "completed":
      return job.outcome === "not_converged"
        ? "The power flow did not converge, so there are no values to show."
        : "The power flow converged. Its result is stored.";
    case "failed":
      return job.failure === null
        ? "The job failed."
        : `${job.failure.message} (${job.failure.code})`;
    case "cancelled":
      return "It was cancelled before a worker started it. Nothing was solved.";
  }
}
