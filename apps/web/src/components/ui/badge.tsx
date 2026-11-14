import type { ReactNode } from "react";

type Tone = "neutral" | "info" | "warn";

const TONES: Record<Tone, string> = {
  neutral: "border-line bg-surface text-muted",
  info: "border-accent/40 bg-accent/10 text-accent",
  warn: "border-warn/40 bg-warn/10 text-warn",
};

export function Badge({
  tone = "neutral",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

const ORIGIN_LABELS = { synthetic: "Synthetic data" } as const;

/** Where a grid's data comes from, as the API states it. Never inferred. */
export function DataOriginBadge({ origin }: { origin: keyof typeof ORIGIN_LABELS }) {
  return (
    <Badge tone="warn" title="Generated or benchmark data. Not measured on any real network.">
      {ORIGIN_LABELS[origin]}
    </Badge>
  );
}
