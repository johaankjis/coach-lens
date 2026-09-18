import type { Metadata } from "next";
import SectionPlaceholder from "../components/section-placeholder";

export const metadata: Metadata = { title: "KPI Tracker | CoachLens AI" };

export default function KpiTrackerPage() {
  return (
    <SectionPlaceholder
      href="/kpi-tracker"
      summary="KPI Tracker will compare later QA outcomes with the original evidence behind each validated diagnosis. Deterministic code will own every comparison; the UI will not compute trends on its own."
      dependsOn={[
        "Outcome evaluation contracts that pair a validated intervention with follow-up QA records",
        "M2 aggregate scoring exposed through the API",
      ]}
    />
  );
}
