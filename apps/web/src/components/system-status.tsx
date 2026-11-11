"use client";

import { useEffect, useState } from "react";
import { API_BASE_URL, fetchSystemStatus, type SystemStatus } from "@/lib/api";

type ViewState = { kind: "loading" } | SystemStatus;

const DATABASE_LABEL = {
  ok: "Connected",
  unavailable: "Unavailable",
  not_migrated: "Reachable, schema not migrated",
  schema_mismatch: "Reachable, schema revision mismatch",
} as const;

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-t border-line py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}

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
      className="max-w-xl rounded-lg border border-line bg-panel p-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="system-status-title" className="text-sm font-medium text-muted">
            Platform status
          </h2>
          <p role="status" className={`mt-1 text-xl font-semibold ${tone}`}>
            {text}
          </p>
        </div>
        <button
          type="button"
          className="rounded border border-line px-3 py-1.5 text-sm hover:bg-surface disabled:opacity-50"
          disabled={state.kind === "loading"}
          onClick={() => {
            setState({ kind: "loading" });
            setAttempt((value) => value + 1);
          }}
        >
          Refresh
        </button>
      </div>

      <dl className="mt-4">
        <Row label="API" value={API_BASE_URL} />
        {state.kind === "ready" || state.kind === "not_ready" ? (
          <>
            <Row label="Database" value={DATABASE_LABEL[state.readiness.database]} />
            <Row label="Schema revision" value={state.readiness.schema_revision ?? "None"} />
            {state.readiness.database === "schema_mismatch" ? (
              <Row
                label="Expected revision"
                value={state.readiness.expected_schema_revision ?? "Unknown"}
              />
            ) : null}
          </>
        ) : null}
        {state.kind === "ready" ? (
          <>
            <Row label="API version" value={state.info.version} />
            <Row label="Environment" value={state.info.environment} />
          </>
        ) : null}
        {state.kind === "unreachable" ? <Row label="Reason" value={state.reason} /> : null}
      </dl>

      {state.kind === "ready" ? (
        <p className="mt-4 text-xs text-muted">{state.info.notice}</p>
      ) : null}
    </section>
  );
}
