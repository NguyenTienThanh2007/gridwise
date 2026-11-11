import type { Metadata } from "next";
import { PlannedFeature } from "@/components/planned-feature";

export const metadata: Metadata = { title: "Monitoring" };

export default function Page() {
  return <PlannedFeature href="/monitoring" />;
}
