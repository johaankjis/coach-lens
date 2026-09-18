import type { Metadata } from "next";
import PracticeWorkspace from "./practice-workspace";

export const metadata: Metadata = {
  title: "Role-Play | CoachLens AI",
  description: "Scripted hands-on practice generated inside the AWS-5 training package.",
};

/** Home and the Training page link here with `?signal=<id>`; without it the backend's first signal is shown. */
export default async function RolePlayPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const requested = params.signal;
  return <PracticeWorkspace signalId={typeof requested === "string" && requested ? requested : null} />;
}
