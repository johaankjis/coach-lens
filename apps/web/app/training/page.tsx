import type { Metadata } from "next";
import TrainingWorkspace from "./training-workspace";

export const metadata: Metadata = {
  title: "Training | CoachLens AI",
  description: "The AWS-5 training package generated for a solution-validated intervention.",
};

/** Home and the Training stage link here with `?signal=<id>`; without it the backend's first signal is shown. */
export default async function TrainingPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const requested = params.signal;
  return <TrainingWorkspace signalId={typeof requested === "string" && requested ? requested : null} />;
}
