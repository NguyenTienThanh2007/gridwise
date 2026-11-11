import type { Metadata } from "next";
import { PlannedFeature } from "@/components/planned-feature";

export const metadata: Metadata = { title: "Simulations" };

export default function Page() {
  return <PlannedFeature href="/simulations" />;
}
