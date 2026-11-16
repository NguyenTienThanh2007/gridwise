import type { ReactNode } from "react";

/**
 * A small state label: status, service state, model position, provenance. One shape for all
 * of them, so states read alike everywhere; the text always says the state, colour only
 * supports it.
 */

export type ChipTone = "neutral" | "accent" | "ok" | "warn" | "bad" | "provenance";

const TONES: Record<ChipTone, string> = {
  neutral: "border-line-strong bg-sunken text-muted",
  accent: "border-accent/35 bg-accent-subtle text-accent",
  ok: "border-ok/35 bg-ok-subtle text-ok",
  warn: "border-warn/35 bg-warn-subtle text-warn",
  bad: "border-bad/35 bg-bad-subtle text-bad",
  provenance: "border-provenance/30 bg-provenance-subtle text-provenance",
};

export function Chip({
  tone = "neutral",
  title,
  children,
}: {
  tone?: ChipTone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={`inline-flex h-5 items-center whitespace-nowrap rounded-control border px-1.5 text-[0.6875rem] font-medium leading-none ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

const ORIGIN_LABELS = { synthetic: "Synthetic data" } as const;

/** Where a grid's data comes from, as the API states it. Never inferred. */
export function DataOriginBadge({ origin }: { origin: keyof typeof ORIGIN_LABELS }) {
  return (
    <Chip tone="provenance" title="Generated or benchmark data. Not measured on any real network.">
      {ORIGIN_LABELS[origin]}
    </Chip>
  );
}
