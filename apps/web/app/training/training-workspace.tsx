"use client";

import Link from "next/link";
import { useInsightSources } from "../components/use-insight-sources";
import { InterventionContext, StagePage, StageUnavailable } from "../components/stage-page";
import DesignWorkspace from "../design-workspace";

/**
 * Displays the AWS-5 training package generated for one validated, solution-reviewed
 * intervention. Generation and every review action stay in Agent Insights; this page only
 * shows what exists and says plainly when nothing does.
 */
export default function TrainingWorkspace({ signalId }: { signalId: string | null }) {
  const load = useInsightSources(signalId);
  return (
    <StagePage
      eyebrow="Training · AWS-5 training designer"
      title="Generated training package"
      lead="The outline, activities, knowledge check, and design status CoachLens produced for a solution-validated training intervention. Generated training is not deployed training."
      load={load}
    >
      {(model) => {
        const insight = model.priority;
        const design = load.sources?.priority?.design ?? null;
        if (!insight)
          return (
            <StageUnavailable
              title="No observed criteria yet"
              detail="Load QA evaluations to begin. A training package exists only after a diagnosis is human validated and its intervention is solution validated."
              insight={null}
            />
          );
        const { training } = insight;
        return (
          <>
            <InterventionContext insight={insight} />
            {training.state === "generated" && design?.training_design ? (
              <>
                <section className="home-card training-package" aria-labelledby="package-title">
                  <div className="home-card-head">
                    <div>
                      <span className="eyebrow">Training package · {training.origin === "fixture" ? "controlled non-AI fixture" : "AI generated"}</span>
                      <h2 id="package-title">What was generated</h2>
                    </div>
                    <Link className="button secondary" href={training.rolePlayHref}>
                      Open role-play script
                    </Link>
                  </div>
                  <p className="quiet">
                    Design status: {training.designStatus.replaceAll("_", " ")}. Independent alignment review is
                    pending. Hands-on practice is shown on the Role-Play page.
                  </p>
                  <DesignWorkspace result={design} signalLabel={insight.criterion} hidePractice />
                </section>
              </>
            ) : training.state === "withheld" ? (
              <StageUnavailable
                title="Training withheld"
                detail={`${training.reason} Review the solution concerns in Agent Insights; a corrected proposal needs a new review run.`}
                insight={insight}
              />
            ) : training.state === "not_applicable" ? (
              <StageUnavailable
                title="Training not applicable"
                detail={`${training.reason} This is not a failed training stage: the validated intervention is a different kind of response.`}
                insight={insight}
              />
            ) : training.state === "permitted" ? (
              <StageUnavailable
                title="Training not generated yet"
                detail={`${training.reason} Generate it from Agent Insights with Design Intervention.`}
                insight={insight}
              />
            ) : training.state === "awaiting_solution" ? (
              <StageUnavailable title="Awaiting solution validation" detail={training.reason} insight={insight} />
            ) : (
              <StageUnavailable
                title="No training package"
                detail={training.state === "generated" ? "The package could not be loaded. Refresh and try again." : training.reason}
                insight={insight}
              />
            )}
          </>
        );
      }}
    </StagePage>
  );
}
