import type { Metadata } from "next";
import { GridListView } from "@/components/grids/grid-list-view";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Grids" };

export default function Page() {
  return (
    <>
      <PageHeader
        title="Grids"
        summary="Stored grid models. Every grid so far is synthetic: generated or benchmark data, not measured on any real network."
      />
      <GridListView />
    </>
  );
}
