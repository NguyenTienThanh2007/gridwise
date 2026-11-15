import type { Metadata } from "next";
import { GridListView } from "@/components/grids/grid-list-view";
import { PageHeader } from "@/components/page-header";

export const metadata: Metadata = { title: "Grids" };

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { deleted } = await searchParams;
  return (
    <>
      <PageHeader
        title="Grids"
        summary="Stored grid models. Every grid so far is synthetic: generated or benchmark data, not measured on any real network."
      />
      <GridListView deleted={deleted === "1"} />
    </>
  );
}
