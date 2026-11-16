"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useRef, useState } from "react";
import { useGrids, useScenarios } from "@/components/simulations/use-names";
import { DataOriginBadge } from "@/components/ui/chip";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState, describeFailure } from "@/components/ui/error-state";
import { Select, TextField } from "@/components/ui/fields";
import { Notice } from "@/components/ui/notice";
import type { ApiFailure } from "@/lib/http/client";
import type { fetchGrids } from "@/lib/resources/grids";
import { describeModification, type fetchScenarios } from "@/lib/resources/scenarios";
import {
  CONFIGURATION_DEFAULTS,
  MAX_ITERATIONS_RANGE,
  TOLERANCE_MAX,
  submitSimulation,
} from "@/lib/resources/simulations";
import { LoadingState } from "@/components/ui/loading-state";

const NORMAL = "normal";

export function toleranceError(text: string): string | null {
  const value = Number(text);
  if (text.trim() === "" || !Number.isFinite(value)) return "Enter a number, for example 1e-8.";
  if (value <= 0 || value > TOLERANCE_MAX) return "Use a value above 0 and at most 0.001 MVA.";
  return null;
}

export function iterationsError(text: string): string | null {
  const value = Number(text);
  const [min, max] = MAX_ITERATIONS_RANGE;
  if (!/^\d+$/.test(text.trim()) || value < min || value > max) {
    return `Use a whole number from ${min} to ${max}.`;
  }
  return null;
}

/** A new key per distinct request: a retry of the same request reuses it, never a new job. */
function newKey(): string {
  return crypto.randomUUID();
}

/**
 * Queues a power-flow simulation of a stored grid, optionally with a scenario. The grid
 * version on screen is sent as If-Match, so the job simulates exactly what the user saw.
 */
export function NewSimulationForm({
  submit = submitSimulation,
  loadGrids,
  loadScenarios,
}: {
  submit?: typeof submitSimulation;
  loadGrids?: typeof fetchGrids;
  loadScenarios?: typeof fetchScenarios;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [grids, reloadGrids] = useGrids(loadGrids);
  const [scenarios] = useScenarios(loadScenarios);

  const [chosenGrid, setChosenGrid] = useState<string | null>(searchParams.get("grid"));
  const [scenarioId, setScenarioId] = useState(searchParams.get("scenario") ?? NORMAL);
  const [tolerance, setTolerance] = useState(String(CONFIGURATION_DEFAULTS.toleranceMva));
  const [iterations, setIterations] = useState(String(CONFIGURATION_DEFAULTS.maxIterations));
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const idempotency = useRef<{ request: string; key: string } | null>(null);

  if (grids.status === "loading") {
    return <LoadingState label="Loading grids…" />;
  }
  if (grids.status === "error") {
    return <ErrorState failure={grids.failure} resource="grids" onRetry={reloadGrids} />;
  }
  if (grids.data.length === 0) {
    return (
      <EmptyState title="There is no grid to simulate">
        <p>
          Load the synthetic demonstration grid with{" "}
          <code className="rounded-control bg-surface px-1">make seed-demo</code>.
        </p>
      </EmptyState>
    );
  }

  const grid = grids.data.find((item) => item.id === chosenGrid) ?? grids.data[0];
  if (grid === undefined) return null;
  const scenarioList = scenarios.status === "ready" ? scenarios.data : [];
  const scenario = scenarioList.find((item) => item.id === scenarioId) ?? null;
  const toleranceProblem = toleranceError(tolerance);
  const iterationsProblem = iterationsError(iterations);
  const blocked = submitting || toleranceProblem !== null || iterationsProblem !== null;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (blocked) return;
    const custom =
      Number(tolerance) !== CONFIGURATION_DEFAULTS.toleranceMva ||
      Number(iterations) !== CONFIGURATION_DEFAULTS.maxIterations;
    const input = {
      gridId: grid.id,
      gridVersion: grid.version,
      scenarioId: scenario?.id ?? null,
      configuration: custom
        ? { toleranceMva: Number(tolerance), maxIterations: Number(iterations) }
        : null,
    };
    const fingerprint = JSON.stringify(input);
    if (idempotency.current?.request !== fingerprint) {
      idempotency.current = { request: fingerprint, key: newKey() };
    }
    setSubmitting(true);
    setFailure(null);
    const result = await submit({ ...input, idempotencyKey: idempotency.current.key });
    if (result.ok) {
      router.push(`/simulations/${result.data.id}`);
      return;
    }
    setSubmitting(false);
    setFailure(result.failure);
  };

  return (
    <form
      onSubmit={onSubmit}
      className="max-w-3xl space-y-6"
      aria-labelledby="new-simulation-title"
    >
      <h2 id="new-simulation-title" className="sr-only">
        New simulation
      </h2>

      <section className="space-y-3 rounded-panel border border-line bg-panel p-4">
        <Select
          wide
          label="Grid"
          value={grid.id}
          onChange={(value) => {
            setChosenGrid(value);
            setFailure(null);
          }}
          options={grids.data.map((item) => ({ value: item.id, label: item.name }))}
        />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <DataOriginBadge origin={grid.dataOrigin} />
          <span>
            Simulates version <span className="tabular-nums">{grid.version}</span> exactly. If the
            grid changes before you submit, you are asked to review it again.
          </span>
        </div>
      </section>

      <section className="space-y-3 rounded-panel border border-line bg-panel p-4">
        <Select
          wide
          label="Scenario"
          value={scenario?.id ?? NORMAL}
          onChange={(value) => {
            setScenarioId(value);
            setFailure(null);
          }}
          options={[
            { value: NORMAL, label: "Normal operation (no changes)" },
            ...scenarioList.map((item) => ({ value: item.id, label: item.name })),
          ]}
        />
        {scenario === null ? (
          <p className="text-sm text-muted">The stored grid is simulated as it is.</p>
        ) : (
          <div className="text-sm">
            <p className="text-muted">
              Changes applied to a copy of the grid before it is simulated:
            </p>
            <ul className="mt-1 list-disc pl-5">
              {scenario.specification.modifications.map((modification, index) => (
                <li key={index}>{describeModification(modification)}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-xs text-muted">
          <Link href="/simulations/scenarios" className="text-accent hover:underline">
            Create or delete scenarios
          </Link>
          . A scenario never changes the stored grid.
        </p>
      </section>

      <fieldset className="space-y-3 rounded-panel border border-line bg-panel p-4">
        <legend className="px-1 text-sm font-medium">Solver options (AC Newton-Raphson)</legend>
        <p className="text-xs text-muted">The engine&apos;s defaults suit most studies.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label="Tolerance (MVA)"
            value={tolerance}
            onChange={setTolerance}
            error={toleranceProblem}
            description="Above 0 and at most 0.001."
          />
          <TextField
            label="Maximum iterations"
            value={iterations}
            onChange={setIterations}
            error={iterationsProblem}
            description="1 to 100."
          />
        </div>
      </fieldset>

      {failure === null ? null : <SubmitFailure failure={failure} onReload={reloadGrids} />}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={blocked}>
          {submitting ? "Queuing…" : "Queue simulation"}
        </Button>
        <p className="text-xs text-muted">
          Queues a power-flow simulation of a copy of the stored model. Nothing is sent to any
          equipment.
        </p>
      </div>
    </form>
  );
}

function SubmitFailure({ failure, onReload }: { failure: ApiFailure; onReload: () => void }) {
  if (failure.kind === "conflict" && failure.status === 412) {
    return (
      <Notice tone="warn" title="Not queued: the grid changed" role="alert">
        <p>
          {failure.currentVersion === null
            ? "The grid has a newer version."
            : `The grid is now version ${failure.currentVersion}.`}{" "}
          Reload to see it, then submit again.
        </p>
        <Button className="mt-2" onClick={onReload}>
          Reload grids
        </Button>
      </Notice>
    );
  }
  if (failure.kind === "invalid" && failure.status === 422) {
    const titles: Record<string, string> = {
      scenario_not_applicable: "Not queued: the scenario names elements this grid does not have",
      simulated_grid_invalid: "Not queued: the grid as the scenario changes it is not valid",
      scenario_not_found: "Not queued: the scenario no longer exists",
      grid_too_large: "Not queued: the simulated grid is too large",
    };
    return (
      <Notice tone="bad" title={titles[failure.code] ?? "Not queued"} role="alert">
        <p>{failure.message}</p>
        {failure.details.length === 0 ? null : (
          <ul className="mt-1 list-disc pl-5">
            {failure.details.map((detail, index) => (
              <li key={index}>
                {detail.message} <code className="text-xs">{detail.type}</code>
              </li>
            ))}
          </ul>
        )}
      </Notice>
    );
  }
  const { title, detail } = describeFailure(failure, "grid");
  return (
    <Notice
      tone="bad"
      title={`Not queued: ${title.charAt(0).toLowerCase()}${title.slice(1)}`}
      role="alert"
    >
      <p>{detail} Submitting again is safe: the same request never makes a second job.</p>
    </Notice>
  );
}
