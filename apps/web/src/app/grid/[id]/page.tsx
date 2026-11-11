import type { Metadata } from "next";
import { PlannedFeature } from "@/components/planned-feature";

export const metadata: Metadata = { title: "Grid detail" };

export default async function GridDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <PlannedFeature
      href="/grid"
      detail={`Requested grid "${id}". No grids exist yet, so nothing can be looked up.`}
    />
  );
}
