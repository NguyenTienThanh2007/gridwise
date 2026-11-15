import type { Metadata } from "next";
import { JobView } from "@/components/simulations/job-view";

export const metadata: Metadata = { title: "Simulation job" };

export default async function Page({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  return <JobView id={jobId} />;
}
