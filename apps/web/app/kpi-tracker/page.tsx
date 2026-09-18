import type { Metadata } from "next";
import OutcomeTracker from "./outcome-tracker";

export const metadata: Metadata = {
  title: "KPI Tracker | CoachLens AI",
  description: "Outcome measurement status and the observed M2 baseline it would be compared against.",
};

export default function KpiTrackerPage() {
  return <OutcomeTracker />;
}
