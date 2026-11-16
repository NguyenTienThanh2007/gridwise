"use client";

import Link from "next/link";
import { useState } from "react";
import { ScenarioForm } from "@/components/simulations/scenario-form";
import { useScenarios } from "@/components/simulations/use-names";
import { Button, buttonClass } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState, describeFailure } from "@/components/ui/error-state";
import { formatTimestamp } from "@/lib/format";
import {
  type Scenario,
  createScenario,
  deleteScenario,
  describeModification,
  type fetchScenarios,
} from "@/lib/resources/scenarios";
import { LoadingState } from "@/components/ui/loading-state";

function ScenarioCard({
  scenario,
  remove,
  onDeleted,
}: {
  scenario: Scenario;
  remove: typeof deleteScenario;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    const result = await remove(scenario.id);
    setBusy(false);
    if (result.ok || result.failure.kind === "not_found") {
      onDeleted();
      return;
    }
    setConfirming(false);
    setProblem(describeFailure(result.failure, "scenario").title);
  };

  return (
    <li className="rounded-panel border border-line bg-panel p-4" data-scenario={scenario.name}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold">{scenario.name}</h3>
          {scenario.description === "" ? null : (
            <p className="mt-0.5 text-sm text-muted">{scenario.description}</p>
          )}
        </div>
        <Link
          href={`/simulations/new?scenario=${scenario.id}`}
          className={buttonClass("secondary", "sm")}
        >
          Simulate with this scenario
        </Link>
      </div>
      <ol className="mt-2 list-decimal pl-5 text-sm">
        {scenario.specification.modifications.map((modification, index) => (
          <li key={index}>{describeModification(modification)}</li>
        ))}
      </ol>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs text-muted">Created {formatTimestamp(scenario.createdAt)}</span>
        {confirming ? null : (
          <Button
            onClick={() => setConfirming(true)}
            aria-label={`Delete scenario ${scenario.name}`}
          >
            Delete
          </Button>
        )}
      </div>
      {confirming ? (
        <div className="mt-3 rounded-control border border-bad/40 bg-bad/5 p-3">
          <p className="text-sm">
            Delete this scenario? Jobs that used it keep their own copy of its changes.
          </p>
          <div className="mt-2 flex gap-2">
            <Button variant="danger" disabled={busy} onClick={() => void run()}>
              {busy ? "Deleting…" : "Confirm delete"}
            </Button>
            <Button disabled={busy} onClick={() => setConfirming(false)}>
              Keep it
            </Button>
          </div>
        </div>
      ) : null}
      {problem === null ? null : (
        <p role="alert" className="mt-2 text-sm font-medium text-bad">
          Not deleted: {problem}
        </p>
      )}
    </li>
  );
}

/** Stored scenarios (immutable) and the form to create one. */
export function ScenariosView({
  load,
  create = createScenario,
  remove = deleteScenario,
}: {
  load?: typeof fetchScenarios;
  create?: typeof createScenario;
  remove?: typeof deleteScenario;
}) {
  const [scenarios, reload] = useScenarios(load);
  const [created, setCreated] = useState<string | null>(null);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section aria-labelledby="scenario-list-title">
        <h2 id="scenario-list-title" className="mb-3 text-section-title">
          Stored scenarios
        </h2>
        {created === null ? null : (
          <p role="status" className="mb-3 text-sm font-medium text-ok">
            Scenario “{created}” created.
          </p>
        )}
        {scenarios.status === "loading" ? (
          <LoadingState label="Loading scenarios…" />
        ) : scenarios.status === "error" ? (
          <ErrorState failure={scenarios.failure} resource="scenarios" onRetry={reload} />
        ) : scenarios.data.length === 0 ? (
          <EmptyState title="No scenario is stored yet">
            <p>Without one, a simulation uses the stored grid as it is (normal operation).</p>
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {scenarios.data.map((scenario) => (
              <ScenarioCard
                key={scenario.id}
                scenario={scenario}
                remove={remove}
                onDeleted={reload}
              />
            ))}
          </ul>
        )}
      </section>
      <ScenarioForm
        create={create}
        onCreated={(scenario) => {
          setCreated(scenario.name);
          reload();
        }}
      />
    </div>
  );
}
