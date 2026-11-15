import type { Metadata } from "next";
import { GridWorkspace } from "@/components/grids/grid-workspace";

export const metadata: Metadata = { title: "Grid assets" };

export default async function GridAssetsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GridWorkspace id={id} tab="assets" />;
}
