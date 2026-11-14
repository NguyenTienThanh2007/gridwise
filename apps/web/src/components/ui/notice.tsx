import type { ReactNode } from "react";

type Tone = "info" | "warn" | "bad";

const TONES: Record<Tone, string> = {
  info: "border-line bg-panel",
  warn: "border-warn/40 bg-warn/5",
  bad: "border-bad/40 bg-bad/5",
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
    <section role={role} className={`max-w-3xl rounded-lg border p-4 ${TONES[tone]}`}>
      <p className="font-medium">{title}</p>
      {children === undefined ? null : <div className="mt-1 text-sm text-muted">{children}</div>}
    </section>
  );
}
