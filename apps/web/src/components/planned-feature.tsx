import { PageHeader } from "@/components/page-header";
import { NAV_ITEMS } from "@/lib/navigation";

/**
 * An honest placeholder: it states what the route will contain and when, and shows no
 * numbers, charts or entities, because none exist in the backend yet.
 */
export function PlannedFeature({ href, detail }: { href: string; detail?: string }) {
  const item = NAV_ITEMS.find((candidate) => candidate.href === href);
  if (item === undefined) throw new Error(`No navigation entry for ${href}`);

  return (
    <>
      <PageHeader title={item.label} summary={item.summary} />
      <section
        aria-label="Implementation status"
        className="max-w-3xl rounded-lg border border-dashed border-line bg-panel p-6"
      >
        <p className="font-medium">Not implemented yet</p>
        <p className="mt-2 text-sm text-muted">
          Planned for roadmap phase {item.phase}. No data is shown here because the backend does not
          provide any yet.
        </p>
        {detail === undefined ? null : <p className="mt-2 text-sm text-muted">{detail}</p>}
      </section>
    </>
  );
}
