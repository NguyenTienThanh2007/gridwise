import type { ReactNode } from "react";

type Tone = "info" | "warn" | "bad";

/** A message in the flow of the page: a coloured edge, not a coloured box. */
const TONES: Record<Tone, string> = {
  info: "border-l-line-strong",
  warn: "border-l-warn",
  bad: "border-l-bad",
};

export function Notice({
  tone = "info",
  title,
  children,
  role,
}: {
  tone?: Tone;
  title: string;
  children?: ReactNode;
  role?: "status" | "alert";
}) {
  return (
    <section
      role={role}
      className={`max-w-3xl rounded-panel border border-line border-l-[3px] bg-panel px-4 py-3 ${TONES[tone]}`}
    >
      <p className="text-label">{title}</p>
      {children === undefined ? null : <div className="mt-1 text-sm text-muted">{children}</div>}
    </section>
  );
}
