"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL, fetchSystemStatus, type SystemStatus } from "@/lib/api";
import { Property, PropertyList } from "@/components/ui/property-list";

type ViewState = { kind: "loading" } | SystemStatus;

const DATABASE_LABEL = {
  ok: "Connected",
  unavailable: "Unavailable",
  not_migrated: "Reachable, schema not migrated",
  schema_mismatch: "Reachable, schema revision mismatch",
} as const;

function headline(state: ViewState): { text: string; tone: string } {
  switch (state.kind) {
    case "loading":
      return { text: "Checking…", tone: "text-muted" };
    case "ready":
      return { text: "Ready", tone: "text-ok" };
    case "not_ready":
      return { text: "Not ready", tone: "text-warn" };
    case "unreachable":
      return { text: "API unreachable", tone: "text-bad" };
  }
}

export function SystemStatusCard({
  load = fetchSystemStatus,
}: {
  load?: () => Promise<SystemStatus>;
}) {
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void load().then((status) => {
      if (!cancelled) setState(status);
    });
    return () => {
      cancelled = true;
    };
  }, [load, attempt]);

  const { text, tone } = headline(state);

  return (
    <section
      aria-labelledby="system-status-title"
      className="max-w-xl rounded-panel border border-line bg-panel p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="system-status-title" className="text-section-title">
            Platform status
          </h2>
          <p role="status" className={`mt-1 text-xl font-semibold ${tone}`}>
            {text}
          </p>
        </div>
        <button
          type="button"
          className="rounded-control border border-line px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-50"
          disabled={state.kind === "loading"}
          onClick={() => {
            setState({ kind: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          Refresh
        </button>
      </div>

      <PropertyList className="mt-4 border-t border-line">
        <Property label="API">{API_BASE_URL}</Property>
        {state.kind === "ready" || state.kind === "not_ready" ? (
          <>
            <Property label="Database">{DATABASE_LABEL[state.readiness.database]}</Property>
            <Property label="Schema revision">{state.readiness.schema_revision ?? "None"}</Property>
            {state.readiness.database === "schema_mismatch" ? (
              <Property label="Expected revision">
                {state.readiness.expected_schema_revision ?? "Unknown"}
              </Property>
            ) : null}
          </>
        ) : null}
        {state.kind === "ready" ? (
          <>
            <Property label="API version">{state.info.version}</Property>
            <Property label="Environment">{state.info.environment}</Property>
          </>
        ) : null}
        {state.kind === "unreachable" ? <Property label="Reason">{state.reason}</Property> : null}
      </PropertyList>

      {state.kind === "ready" ? (
        <p className="mt-4 text-xs text-muted">{state.info.notice}</p>
      ) : null}
    </section>
  );
}
