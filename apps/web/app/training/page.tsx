import type { Metadata } from "next";
import SectionPlaceholder from "../components/section-placeholder";

export const metadata: Metadata = { title: "Training | CoachLens AI" };

export default function TrainingPage() {
  return (
    <SectionPlaceholder
      href="/training"
      summary="Training will show validated interventions and the training designs built from them, each traced back to the human-validated diagnosis and its QA evidence. Today an M5 proposal is visible only inside Agent Insights after a diagnosis is approved."
      dependsOn={[
        "AWS-4 intervention validation, so a training decision is validated rather than proposed",
        "AWS-5 training designer status, so outlines, activities, and practice specs have a delivery state",
      ]}
    />
  );
}
