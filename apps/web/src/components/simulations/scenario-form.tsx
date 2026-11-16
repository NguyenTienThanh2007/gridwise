"use client";

import { type FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { RadioGroup, Select, TextArea, TextField } from "@/components/ui/fields";
import { Notice } from "@/components/ui/notice";
import { describeFailure } from "@/components/ui/error-state";
import type { ApiFailure } from "@/lib/http/client";
import { DESCRIPTION_MAX, NAME_MAX, descriptionError, nameError } from "@/lib/resources/assets";
import { type Scenario, createScenario } from "@/lib/resources/scenarios";
import {
  CHANGE_TYPE_LABELS,
  type DraftChange,
  ELEMENT_TYPE_LABELS,
  MAX_MODIFICATIONS,
  SCENARIO_ELEMENT_TYPES,
  blankChange,
  changeErrors,
  toModification,
} from "@/lib/scenario-draft";

const TYPES = Object.keys(CHANGE_TYPE_LABELS) as DraftChange["type"][];

/** Server-side reasons for one change, from `details[].location = ["body", "modifications", i]`. */
function serverErrors(failure: ApiFailure | null, index: number): string[] {
  if (failure?.kind !== "invalid") return [];
  return failure.details
    .filter((detail) => detail.location[1] === "modifications" && detail.location[2] === index)
    .map((detail) => `${detail.message} (${detail.type})`);
}

/** Creates an immutable scenario: a name and an ordered list of changes. */
export function ScenarioForm({
  onCreated,
  create = createScenario,
}: {
  onCreated: (scenario: Scenario) => void;
  create?: typeof createScenario;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [changes, setChanges] = useState<DraftChange[]>([blankChange(1)]);
  const [nextId, setNextId] = useState(2);
  const [attempted, setAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const update = (id: number, patch: Partial<DraftChange>) =>
    setChanges((all) => all.map((change) => (change.id === id ? { ...change, ...patch } : change)));
  const nameProblem = attempted || name !== "" ? nameError(name) : null;
  const nameTaken =
    failure?.kind === "conflict" && failure.code === "scenario_name_conflict"
      ? "Another scenario already has this name."
      : null;
  const errors = changes.map(changeErrors);
  const invalid =
    nameError(name) !== null ||
    descriptionError(description) !== null ||
    changes.length === 0 ||
    errors.some((e) => Object.keys(e).length > 0);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setAttempted(true);
    if (invalid || saving) return;
    setSaving(true);
    setFailure(null);
    const result = await create({ name, description, modifications: changes.map(toModification) });
    setSaving(false);
    if (!result.ok) {
      setFailure(result.failure);
      return;
    }
    setName("");
    setDescription("");
    setChanges([blankChange(nextId)]);
    setNextId((value) => value + 1);
    setAttempted(false);
    onCreated(result.data);
  };

  return (
    <form
      onSubmit={onSubmit}
      aria-labelledby="scenario-form-title"
      className="space-y-4 rounded-panel border border-line bg-panel p-4"
    >
      <h2 id="scenario-form-title" className="mb-2 text-section-title">
        New scenario
      </h2>
      <p className="text-sm text-muted">
        A scenario changes a copy of a grid before it is simulated, never the stored grid. Switch
        positions and service states are changed in the simulated copy only; nothing is sent to any
        equipment. Scenarios cannot be edited: create a new one instead.
      </p>
      <TextField
        label="Name"
        value={name}
        onChange={setName}
        error={nameProblem ?? nameTaken}
        maxLength={NAME_MAX}
      />
      <TextArea
        label="Description"
        value={description}
        onChange={setDescription}
        error={descriptionError(description)}
        maxLength={DESCRIPTION_MAX}
      />

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Changes, applied in order</h3>
        {changes.map((change, index) => {
          const own = attempted ? (errors[index] ?? {}) : {};
          const server = serverErrors(failure, index);
          return (
            <fieldset key={change.id} className="space-y-3 rounded-control border border-line p-3">
              <legend className="px-1 text-sm font-medium">Change {index + 1}</legend>
              <div className="flex items-end gap-3">
                <Select
                  wide
                  label="Kind of change"
                  value={change.type}
                  onChange={(type) => update(change.id, { type })}
                  options={TYPES.map((type) => ({ value: type, label: CHANGE_TYPE_LABELS[type] }))}
                />
                {changes.length > 1 ? (
                  <Button
                    onClick={() => setChanges((all) => all.filter((item) => item.id !== change.id))}
                    aria-label={`Remove change ${index + 1}`}
                  >
                    Remove
                  </Button>
                ) : null}
              </div>
              {change.type === "scale_loads" || change.type === "scale_generation" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField
                    label="Factor"
                    value={change.factor}
                    onChange={(factor) => update(change.id, { factor })}
                    error={own.factor}
                    description={
                      change.type === "scale_loads"
                        ? "Multiplies P and Q. Above 0, at most 100."
                        : "Multiplies active power. 0 to 100."
                    }
                  />
                  <TextField
                    label="Element keys (optional)"
                    value={change.keys}
                    onChange={(keys) => update(change.id, { keys })}
                    error={own.keys}
                    description={`Separated by commas. Empty: every ${change.type === "scale_loads" ? "load" : "generator"}.`}
                  />
                  {change.type === "scale_generation" ? (
                    <Select
                      wide
                      label="Only generators in control mode"
                      value={change.controlMode}
                      onChange={(controlMode) => update(change.id, { controlMode })}
                      options={[
                        { value: "", label: "Any control mode" },
                        { value: "constant_power", label: "Constant power" },
                        { value: "voltage_control", label: "Voltage control" },
                      ]}
                    />
                  ) : null}
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2">
                  {change.type === "set_in_service" ? (
                    <Select
                      wide
                      label="Element type"
                      value={change.elementType}
                      onChange={(elementType) => update(change.id, { elementType })}
                      options={SCENARIO_ELEMENT_TYPES.map((type) => ({
                        value: type,
                        label: ELEMENT_TYPE_LABELS[type],
                      }))}
                    />
                  ) : null}
                  <TextField
                    label={change.type === "set_switch" ? "Switch key" : "Element key"}
                    value={change.key}
                    onChange={(key) => update(change.id, { key })}
                    error={own.key}
                  />
                  <RadioGroup<"yes" | "no">
                    legend={
                      change.type === "set_switch"
                        ? "Model position in the simulated copy"
                        : "Service state in the simulated copy"
                    }
                    value={change.flag ? "yes" : "no"}
                    onChange={(value) => update(change.id, { flag: value === "yes" })}
                    options={
                      change.type === "set_switch"
                        ? [
                            { value: "yes", label: "Closed" },
                            { value: "no", label: "Open" },
                          ]
                        : [
                            { value: "yes", label: "In service" },
                            { value: "no", label: "Out of service" },
                          ]
                    }
                  />
                </div>
              )}
              {server.length === 0 ? null : (
                <ul className="list-disc pl-5 text-xs font-medium text-bad">
                  {server.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              )}
            </fieldset>
          );
        })}
        {attempted && changes.length === 0 ? (
          <p className="text-xs font-medium text-bad">
            Add at least one change. Normal operation needs no scenario.
          </p>
        ) : null}
        <Button
          disabled={changes.length >= MAX_MODIFICATIONS}
          onClick={() => {
            setChanges((all) => [...all, blankChange(nextId)]);
            setNextId((value) => value + 1);
          }}
        >
          Add change
        </Button>
      </div>

      {failure === null || nameTaken !== null ? null : (
        <Notice tone="bad" title="Not created" role="alert">
          <p>
            {failure.kind === "invalid" && failure.code === "scenario_invalid"
              ? "The engine refused some changes; see the reasons under each change."
              : describeFailure(failure, "scenario").detail}
          </p>
        </Notice>
      )}

      <Button type="submit" variant="primary" disabled={saving}>
        {saving ? "Creating…" : "Create scenario"}
      </Button>
    </form>
  );
}
