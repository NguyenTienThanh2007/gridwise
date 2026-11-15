import type { Metadata } from "next";
import { GridWorkspace } from "@/components/grids/grid-workspace";

export const metadata: Metadata = { title: "Grid settings" };

export default async function GridSettingsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GridWorkspace id={id} tab="settings" />;
}
