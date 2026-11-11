import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SystemStatusCard } from "@/components/system-status";
import { fetchSystemStatus, type SystemStatus } from "@/lib/api";

const READY: SystemStatus = {
  kind: "ready",
  readiness: {
    status: "ready",
    database: "ok",
    schema_revision: "0001",
    expected_schema_revision: "0001",
  },
  info: {
    version: "0.1.0",
    environment: "test",
    operating_mode: "simulation_and_decision_support",
    notice: "Decision support only.",
  },
};

describe("SystemStatusCard", () => {
  it("shows a checking state before the API answers", () => {
    render(<SystemStatusCard load={() => new Promise<SystemStatus>(() => undefined)} />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking…");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  });

  it("shows database, revision, version and the safety notice when ready", async () => {
    render(<SystemStatusCard load={async () => READY} />);
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("0001")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("Decision support only.")).toBeInTheDocument();
  });

  it("explains a database outage without inventing other details", async () => {
    const status: SystemStatus = {
      kind: "not_ready",
      readiness: {
        status: "not_ready",
        database: "unavailable",
        schema_revision: null,
        expected_schema_revision: "0001",
      },
    };
    render(<SystemStatusCard load={async () => status} />);
    expect(await screen.findByText("Not ready")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.queryByText("API version")).not.toBeInTheDocument();
  });

  it("reloads when Refresh is pressed", async () => {
    const load = vi
      .fn<() => Promise<SystemStatus>>()
      .mockResolvedValueOnce({ kind: "unreachable", reason: "No response from the API" })
      .mockResolvedValueOnce(READY);
    render(<SystemStatusCard load={load} />);
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();

    screen.getByRole("button", { name: "Refresh" }).click();
    expect(await screen.findByText("Ready")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("shows both revisions when the schema does not match this build", async () => {
    const status: SystemStatus = {
      kind: "not_ready",
      readiness: {
        status: "not_ready",
        database: "schema_mismatch",
        schema_revision: "0001",
        expected_schema_revision: "0002",
      },
    };
    render(<SystemStatusCard load={async () => status} />);
    expect(await screen.findByText("Not ready")).toBeInTheDocument();
    expect(screen.getByText("Reachable, schema revision mismatch")).toBeInTheDocument();
    expect(screen.getByText("0001")).toBeInTheDocument();
    expect(screen.getByText("0002")).toBeInTheDocument();
  });

  it("recovers from an API that never responds: reports it and re-enables Refresh", async () => {
    const neverResponds = ((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
      })) as typeof fetch;
    const load = vi.fn(() => fetchSystemStatus(neverResponds, "http://api.test", 50));

    render(<SystemStatusCard load={load} />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking…");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();

    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
    expect(screen.getByText("No response within 0.1 seconds")).toBeInTheDocument();
    const refresh = screen.getByRole("button", { name: "Refresh" });
    expect(refresh).toBeEnabled();

    refresh.click();
    expect(await screen.findByText("Checking…")).toBeInTheDocument();
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });
});
