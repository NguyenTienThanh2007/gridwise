import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { JobView } from "@/components/simulations/job-view";
import type { ApiResult } from "@/lib/http/client";
import { type Job, decodeJob, type cancelJob, type fetchJob } from "@/lib/resources/simulations";
import { COMPLETED, FIXTURE_JOB_ID, fixtureJob } from "@/test/fixtures/jobs";

function answer(overrides: Record<string, unknown> = {}): ApiResult<Job> {
  const data = decodeJob(fixtureJob(overrides));
  if (data === null) throw new Error("fixture does not decode");
  return { ok: true, status: 200, data, etag: null, location: null, headers: new Headers() };
}

const noGrids = async () => ({ ok: false as const, failure: { kind: "aborted" as const } });

function view(load: typeof fetchJob, cancel?: typeof cancelJob) {
  render(<JobView id={FIXTURE_JOB_ID} load={load} cancel={cancel} loadGrids={noGrids} />);
}

describe("JobView", () => {
  it("explains a queued job and offers to cancel it, after confirmation", async () => {
    const load = vi
      .fn<typeof fetchJob>()
      .mockResolvedValueOnce(answer())
      .mockResolvedValue(
        answer({
          status: "cancelled",
          cancelled_at: "2026-11-15T04:58:03Z",
          finished_at: "2026-11-15T04:58:03Z",
        }),
      );
    const cancel = vi.fn<typeof cancelJob>(async () => answer({ status: "cancelled" }));
    view(load, cancel);
    expect(
      await screen.findByText(
        "Waiting for a worker to pick it up. A queued job can still be cancelled.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("No worker has started this job yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel job" }));
    expect(cancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));
    expect(
      await screen.findByText(/It was cancelled before a worker started it/),
    ).toBeInTheDocument();
    expect(cancel).toHaveBeenCalledWith(FIXTURE_JOB_ID);
    expect(screen.queryByRole("button", { name: "Cancel job" })).not.toBeInTheDocument();
  });

  it("explains a refused cancel", async () => {
    const cancel = vi.fn<typeof cancelJob>(async () => ({
      ok: false,
      failure: {
        kind: "conflict",
        status: 409,
        code: "job_not_cancellable",
        message: "x",
        details: [{ location: ["status"], message: "The job is running", type: "running" }],
        currentVersion: null,
      },
    }));
    view(async () => answer(), cancel);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel job" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm cancel" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The job is already running: only a queued job can be cancelled.",
    );
  });

  it("offers no cancel for a running job", async () => {
    view(async () => answer({ status: "running", attempt: 1, started_at: "2026-11-15T04:58:01Z" }));
    expect(
      await screen.findByText(/A worker is solving it \(attempt 1 of 3\)/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel job" })).not.toBeInTheDocument();
  });

  it("shows how a completed job ran, and promises no values it does not have", async () => {
    view(async () => answer(COMPLETED));
    expect(await screen.findAllByText("Completed, converged")).toHaveLength(2);
    expect(screen.getByText("pandapower 3.5.6")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Attempts" })).toHaveTextContent("Completed");
    expect(screen.getByText(/AC Newton-Raphson, tolerance/)).toBeInTheDocument();
    expect(screen.getByText("Normal operation (no changes)")).toBeInTheDocument();
  });

  it("says a run that did not converge has no values", async () => {
    view(async () => answer({ ...COMPLETED, outcome: "not_converged" }));
    expect(
      await screen.findByText(
        "This run did not converge: there are no values, and none will be shown.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the catalogue's failure message", async () => {
    view(async () =>
      answer({
        status: "failed",
        attempt: 1,
        failure: {
          code: "execution_timeout",
          message: "The computation did not finish within the time limit.",
        },
      }),
    );
    expect(
      await screen.findByText(
        "The computation did not finish within the time limit. (execution_timeout)",
      ),
    ).toBeInTheDocument();
  });

  it("says when the grid changed or was deleted since", async () => {
    view(async () =>
      answer({
        source: {
          grid_id: null,
          grid_version: 3,
          topology_hash: "ab".repeat(32),
          status: "deleted",
        },
      }),
    );
    expect(await screen.findByText("Deleted grid")).toBeInTheDocument();
    expect(
      screen.getByText("The grid has since been deleted; this job keeps its own copy."),
    ).toBeInTheDocument();
  });

  it("makes no request for an id that cannot be a job", async () => {
    const load = vi.fn<typeof fetchJob>();
    render(<JobView id="not-a-job" load={load} loadGrids={noGrids} />);
    expect(
      await screen.findByRole("heading", { level: 1, name: "Job not found" }),
    ).toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });
});
