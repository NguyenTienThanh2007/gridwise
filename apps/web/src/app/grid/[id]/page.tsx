import type { Metadata } from "next";
import { GridDetailView } from "@/components/grids/grid-detail-view";

export const metadata: Metadata = { title: "Grid" };

export default async function GridDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GridDetailView id={id} />;
}
