import type { Metadata } from "next";
import ReviewWorkspace from "../review-workspace";

export const metadata: Metadata = {
  title: "Agent Insights | CoachLens AI",
  description: "Deep diagnostic workspace: evidence, hypotheses, semantic review, and human validation.",
};

/**
 * Agent Insights is the existing three-column review workspace. Home links here with
 * `?signal=<id>` so a priority insight opens on the signal it summarized.
 */
export default async function AgentInsightsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const requested = params.signal;
  const initialSignalId = typeof requested === "string" && requested ? requested : null;
  return <ReviewWorkspace initialSignalId={initialSignalId} />;
}
