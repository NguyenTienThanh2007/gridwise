import type { Metadata } from "next";
import { PlannedFeature } from "@/components/planned-feature";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return <PlannedFeature href="/analytics" />;
}
