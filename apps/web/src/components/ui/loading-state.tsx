/** A quiet loading line: no spinner, nothing that moves. Announced to screen readers. */
export function LoadingState({ label }: { label: string }) {
  return (
    <p role="status" className="py-2 text-sm text-muted">
      {label}
    </p>
  );
}
