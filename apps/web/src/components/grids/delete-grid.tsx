"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useId, useState } from "react";
import { WriteFailure } from "@/components/assets/write-failure";
import { Button } from "@/components/ui/button";
import type { ApiFailure } from "@/lib/http/client";
import { deleteGrid } from "@/lib/resources/assets";
import type { Grid } from "@/lib/resources/grids";

/** The seeded demonstration grid (gridwise_api.seed.DEMO_GRID_ID). */
const DEMO_GRID_ID = "d0000000-0000-4000-8000-000000000002";

/**
 * Deleting a grid: explained, confirmed by typing the grid's exact name, and sent with the
 * version on screen so a grid changed by someone else is never deleted unseen.
 */
export function DeleteGrid({
  grid,
  onReload,
  remove = deleteGrid,
}: {
  grid: Grid;
  onReload: () => void;
  remove?: typeof deleteGrid;
}) {
  const router = useRouter();
  const confirmId = useId();
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [failure, setFailure] = useState<ApiFailure | null>(null);
  const confirmed = typed === grid.name;

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!confirmed || deleting) return;
    setDeleting(true);
    setFailure(null);
    const result = await remove(grid.id, grid.version);
    if (result.ok) {
      router.push("/grid?deleted=1");
      return;
    }
    setDeleting(false);
    setFailure(result.failure);
  };

  return (
    <section aria-labelledby="delete-grid-title" className="max-w-2xl">
      <h2 id="delete-grid-title" className="mb-3 text-lg font-semibold text-bad">
        Delete grid
      </h2>
      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border border-bad/40 bg-bad/5 p-4">
        <p className="text-sm">
          Deletes this grid and all of its elements. <strong>This cannot be undone.</strong>{" "}
          Simulation jobs keep their own copies of the input and their results; they will show their
          source grid as deleted.
        </p>
        {grid.id === DEMO_GRID_ID ? (
          <p className="text-sm text-muted">
            This is the synthetic demonstration grid. It can be recreated with{" "}
            <code className="rounded bg-surface px-1">make seed-demo</code>.
          </p>
        ) : null}
        <div>
          <label htmlFor={confirmId} className="block text-sm font-medium">
            Type the grid&apos;s name to confirm: <span className="font-mono">{grid.name}</span>
          </label>
          <input
            id={confirmId}
            type="text"
            value={typed}
            autoComplete="off"
            onChange={(event) => setTyped(event.target.value)}
            className="mt-1 w-full rounded border border-line px-2 py-1.5 text-sm"
          />
        </div>
        {failure === null ? null : (
          <WriteFailure
            failure={failure}
            onReloadAndReview={() => {
              setFailure(null);
              setTyped("");
              onReload();
            }}
            onDiscard={() => {
              setFailure(null);
              setTyped("");
            }}
          />
        )}
        <Button type="submit" variant="danger" disabled={!confirmed || deleting}>
          {deleting ? "Deleting…" : "Delete grid permanently"}
        </Button>
      </form>
    </section>
  );
}
