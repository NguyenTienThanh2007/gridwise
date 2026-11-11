import type { Metadata } from "next";
import { PlannedFeature } from "@/components/planned-feature";

export const metadata: Metadata = { title: "Settings" };

export default function Page() {
  return <PlannedFeature href="/settings" />;
}
