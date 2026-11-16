"use client";

import { type FormEvent, useState } from "react";
import { WriteFailure } from "@/components/assets/write-failure";
import { Button } from "@/components/ui/button";
import { TextArea, TextField } from "@/components/ui/fields";
import type { ApiFailure } from "@/lib/http/client";
import {
  DESCRIPTION_MAX,
  NAME_MAX,
  descriptionError,
  nameError,
  updateGrid,
} from "@/lib/resources/assets";
import type { Grid } from "@/lib/resources/grids";

/** The grid's name and description. Only changed fields are sent, with If-Match. */
export function GridSettings({
  grid,
  onSaved,
  update = updateGrid,
}: {
  grid: Grid;
  onSaved: () => void;
  update?: typeof updateGrid;
}) {
  const [name, setName] = useState(grid.name);
  const [description, setDescription] = useState(grid.description);
  const [baseVersion, setBaseVersion] = useState(grid.version);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  const nameChanged = name !== grid.name;
  const descriptionChanged = description !== grid.description;
  const nameProblem = nameChanged ? nameError(name) : null;
  const descriptionProblem = descriptionError(description);
  const nameTaken =
    failure?.kind === "conflict" && failure.code === "grid_name_conflict"
      ? "Another grid already has this name."
      : null;
  const changed = nameChanged || descriptionChanged;
  const blocked = !changed || nameProblem !== null || descriptionProblem !== null || saving;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (blocked) return;
    setSaving(true);
    setFailure(null);
    setSavedVersion(null);
    const result = await update(
      grid.id,
      { ...(nameChanged ? { name } : {}), ...(descriptionChanged ? { description } : {}) },
      baseVersion,
    );
    setSaving(false);
    if (result.ok) {
      setBaseVersion(result.data.version);
      setSavedVersion(result.data.version);
      onSaved();
    } else {
      setFailure(result.failure);
    }
  };

  return (
    <section aria-labelledby="grid-settings-title" className="max-w-2xl">
      <h2 id="grid-settings-title" className="mb-3 text-section-title">
        Name and description
      </h2>
      <form onSubmit={onSubmit} className="space-y-4 rounded-panel border border-line bg-panel p-4">
        <TextField
          label="Name"
          value={name}
          onChange={(value) => {
            setName(value);
            if (nameTaken !== null) setFailure(null);
          }}
          error={nameProblem ?? nameTaken}
          maxLength={NAME_MAX}
          description="A rename gives the grid a new topology hash: the name is part of the stored model."
        />
        <TextArea
          label="Description"
          value={description}
          onChange={setDescription}
          error={descriptionProblem}
          maxLength={DESCRIPTION_MAX}
        />
        {failure === null || nameTaken !== null ? null : (
          <WriteFailure
            failure={failure}
            onReloadAndReview={(currentVersion) => {
              if (currentVersion !== null) setBaseVersion(currentVersion);
              setFailure(null);
              onSaved();
            }}
            onDiscard={() => {
              setName(grid.name);
              setDescription(grid.description);
              setFailure(null);
            }}
          />
        )}
        {savedVersion === null ? null : (
          <p role="status" className="text-sm font-medium text-ok">
            Saved. The grid is now version {savedVersion}.
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" disabled={blocked}>
            {saving ? "Saving…" : "Save"}
          </Button>
          <Button
            disabled={!changed || saving}
            onClick={() => {
              setName(grid.name);
              setDescription(grid.description);
              setFailure(null);
            }}
          >
            Cancel
          </Button>
        </div>
      </form>
    </section>
  );
}
