import type { Metadata } from "next";
import SectionPlaceholder from "../components/section-placeholder";

export const metadata: Metadata = { title: "Resources | CoachLens AI" };

export default function ResourcesPage() {
  return (
    <SectionPlaceholder
      href="/resources"
      summary="Resources will hold the CoachLens methodology: how deterministic counts, AI hypotheses, semantic evidence review, and human validation fit together, plus the evidence privacy policy. The repository docs folder holds this material today."
      dependsOn={[
        "An in-product rendering of the architecture and milestone guides",
        "The evidence privacy boundary written for reviewers rather than engineers",
      ]}
    />
  );
}
