import type { Metadata } from "next";
import SectionPlaceholder from "../components/section-placeholder";

export const metadata: Metadata = { title: "Role-Play | CoachLens AI" };

export default function RolePlayPage() {
  return (
    <SectionPlaceholder
      href="/role-play"
      summary="Role-Play will let agents practice the validated target behaviors against the practice scenarios and personas a training design specifies. No simulation runs in this build."
      dependsOn={[
        "AWS-5 practice scenarios with a delivery state",
        "A simulation runtime and a rubric scoring boundary that keeps human judgement in the loop",
      ]}
    />
  );
}
