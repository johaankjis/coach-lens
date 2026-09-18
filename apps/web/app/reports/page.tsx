import type { Metadata } from "next";
import SectionPlaceholder from "../components/section-placeholder";

export const metadata: Metadata = { title: "Reports | CoachLens AI" };

export default function ReportsPage() {
  return (
    <SectionPlaceholder
      href="/reports"
      summary="Reports will summarize impact across the team: which diagnoses were validated, which interventions ran, and how outcomes moved. Nothing is reported until outcome evaluation exists."
      dependsOn={[
        "Outcome evaluation results",
        "AWS-6 alignment review so reported training is known to match its diagnosis",
      ]}
    />
  );
}
