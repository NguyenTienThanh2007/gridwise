import type { Metadata } from "next";
import { PlannedFeature } from "@/components/planned-feature";

export const metadata: Metadata = { title: "Assets" };

export default function Page() {
  return <PlannedFeature href="/assets" />;
}
