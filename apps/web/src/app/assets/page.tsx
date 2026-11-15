import type { Metadata } from "next";
import { GridListView } from "@/components/grids/grid-list-view";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Assets" };

export default function Page() {
  return (
    <>
      <PageHeader
        title="Assets"
        summary="Every asset belongs to one grid. Choose a grid to see and edit its assets."
      />
      <GridListView section="assets" />
    </>
  );
}
