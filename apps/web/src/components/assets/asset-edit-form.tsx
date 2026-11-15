"use client";

import { type FormEvent, useState } from "react";
import { SINGULAR } from "@/components/network/describe";
import { WriteFailure } from "@/components/assets/write-failure";
import { Button } from "@/components/ui/button";
import { RadioGroup, TextField } from "@/components/ui/fields";
import { Notice } from "@/components/ui/notice";
import type { ApiFailure } from "@/lib/http/client";
import type { NetworkElement } from "@/lib/network/graph";
import type { ElementRef } from "@/lib/network/selection";
import { type AssetChange, NAME_MAX, nameError, updateAsset } from "@/lib/resources/assets";

type Position = "closed" | "open";
type Service = "in" | "out";

/**
 * Edits exactly what the API accepts for one element: its name, and either its service
 * state or, for a switch, its position in the stored simulation model. A state change is
 * reviewed before it is saved. The version the form was opened with is sent as If-Match.
 */
export function AssetEditForm({
  gridId,
  version,
  target,
  element,
  onSaved,
  onCancel,
  onReload,
  update = updateAsset,
}: {
  gridId: string;
  version: number;
  target: ElementRef;
  element: NetworkElement;
  onSaved: (newVersion: number) => void;
  onCancel: () => void;
  onReload: () => void;
  update?: typeof updateAsset;
}) {
  const isSwitch = "closed" in element;
  const storedPosition: Position = isSwitch && element.closed ? "closed" : "open";
  const storedService: Service = !isSwitch && element.inService ? "in" : "out";

  const [name, setName] = useState(element.name);
  const [position, setPosition] = useState<Position>(storedPosition);
  const [service, setService] = useState<Service>(storedService);
  const [baseVersion, setBaseVersion] = useState(version);
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);

  const nameChanged = name !== element.name;
  const stateChanged = isSwitch ? position !== storedPosition : service !== storedService;
  const changed = nameChanged || stateChanged;
  const error = nameChanged ? nameError(name) : null;
  const kind = SINGULAR[target.type].toLowerCase();

  const change: AssetChange = isSwitch
    ? {
        kind: "switch",
        ...(nameChanged ? { name } : {}),
        ...(stateChanged ? { closed: position === "closed" } : {}),
      }
    : {
        kind: "element",
        ...(nameChanged ? { name } : {}),
        ...(stateChanged ? { inService: service === "in" } : {}),
      };

  const save = async () => {
    setSaving(true);
    setFailure(null);
    const result = await update(gridId, target.type, target.key, change, baseVersion);
    setSaving(false);
    setReviewing(false);
    if (result.ok) onSaved(result.data.gridVersion);
    else setFailure(result.failure);
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!changed || error !== null || saving) return;
    if (stateChanged && !reviewing) {
      setReviewing(true);
      return;
    }
    void save();
  };

  return (
    <form
      onSubmit={onSubmit}
      aria-label={`Edit ${kind} ${element.key}`}
      className="mt-4 space-y-4 border-t border-line pt-4"
    >
      <h4 className="text-sm font-semibold">Edit {kind}</h4>
      <TextField
        label="Name"
        value={name}
        onChange={(value) => {
          setName(value);
          setReviewing(false);
        }}
        error={error}
        maxLength={NAME_MAX}
        description={nameChanged ? `Stored now: ${element.name}` : undefined}
      />
      {isSwitch ? (
        <RadioGroup<Position>
          legend="Model position"
          value={position}
          onChange={(value) => {
            setPosition(value);
            setReviewing(false);
          }}
          options={[
            { value: "closed", label: "Closed" },
            { value: "open", label: "Open" },
          ]}
          description={`Position in the stored simulation model, not a command to any equipment. Stored now: ${storedPosition}.`}
        />
      ) : (
        <RadioGroup<Service>
          legend="Service state"
          value={service}
          onChange={(value) => {
            setService(value);
            setReviewing(false);
          }}
          options={[
            { value: "in", label: "In service" },
            { value: "out", label: "Out of service" },
          ]}
          description={`State in the stored simulation model. Stored now: ${storedService === "in" ? "in service" : "out of service"}.`}
        />
      )}

      {reviewing ? (
        <Notice tone="warn" title="Review this change" role="status">
          <p>
            {isSwitch
              ? `Sets ${element.name} to ${position} in the stored simulation model only. Nothing is sent to any equipment.`
              : `Takes ${element.name} ${service === "in" ? "into" : "out of"} service in the stored simulation model only. Nothing is sent to any equipment.`}{" "}
            Simulations submitted after this use the new state; earlier ones keep theirs.
          </p>
        </Notice>
      ) : null}

      {failure === null ? null : (
        <WriteFailure
          failure={failure}
          onReloadAndReview={(currentVersion) => {
            if (currentVersion !== null) setBaseVersion(currentVersion);
            setFailure(null);
            onReload();
          }}
          onDiscard={onCancel}
        />
      )}

      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={!changed || error !== null || saving}>
          {saving
            ? "Saving…"
            : reviewing
              ? "Confirm and save"
              : stateChanged
                ? "Review change"
                : "Save"}
        </Button>
        <Button onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </div>
      <p className="text-xs text-muted">
        Saving as a change to version {baseVersion}. Electrical parameters are not editable here.
      </p>
    </form>
  );
}
