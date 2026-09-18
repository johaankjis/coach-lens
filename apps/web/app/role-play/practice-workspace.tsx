"use client";

import Link from "next/link";
import { useInsightSources } from "../components/use-insight-sources";
import { InterventionContext, StagePage, StageUnavailable } from "../components/stage-page";
import PracticeScript from "../practice-script";

/**
 * Displays the hands-on practice scenarios inside the AWS-5 training package as facilitator
 * scripts. There is no simulation runtime and no scoring; a person reads the script.
 */
export default function PracticeWorkspace({ signalId }: { signalId: string | null }) {
  const load = useInsightSources(signalId);
  return (
    <StagePage
      eyebrow="Role-Play · AWS-5 practice scenarios"
      title="Hands-on practice script"
      lead="The scripted rehearsal CoachLens generated for the validated target behaviors: a fictional persona, an opening line, scripted turns with expected learner behaviors and facilitator cues, completion criteria, and a rubric. A facilitator runs it; nothing here simulates or scores."
      load={load}
    >
      {(model) => {
        const insight = model.priority;
        const design = load.sources?.priority?.design ?? null;
        if (!insight)
          return (
            <StageUnavailable
              title="No observed criteria yet"
              detail="Load QA evaluations to begin. Practice scenarios exist only inside a generated training package."
              insight={null}
            />
          );
        const { training } = insight;
        const trainingDesign = design?.training_design ?? null;
        return (
          <>
            <InterventionContext insight={insight} />
            {training.state === "generated" && trainingDesign ? (
              <section className="home-card practice-package" aria-labelledby="practice-title">
                <div className="home-card-head">
                  <div>
                    <span className="eyebrow">
                      {trainingDesign.practice_scenarios.length} scenario
                      {trainingDesign.practice_scenarios.length === 1 ? "" : "s"} ·{" "}
                      {training.origin === "fixture" ? "controlled non-AI fixture" : "AI generated"}
                    </span>
                    <h2 id="practice-title">What the learner will rehearse</h2>
                  </div>
                  <Link className="button secondary" href={training.trainingHref}>
                    Open training package
                  </Link>
                </div>
                <p className="quiet">
                  Personas are fictional and were generated for practice; they are not ResultsCX members.
                  Independent alignment review of this package is pending.
                </p>
                {trainingDesign.practice_scenarios.map((scenario) => (
                  <PracticeScript
                    key={scenario.scenario_id}
                    scenario={scenario}
                    behaviors={trainingDesign.target_behaviors}
                    fixture={training.origin === "fixture"}
                  />
                ))}
              </section>
            ) : training.state === "withheld" ? (
              <StageUnavailable
                title="Practice withheld"
                detail={`${training.reason} No practice scenario was generated.`}
                insight={insight}
              />
            ) : training.state === "not_applicable" ? (
              <StageUnavailable
                title="Practice not applicable"
                detail={`${training.reason} No practice scenario is generated for a non-training intervention.`}
                insight={insight}
              />
            ) : (
              <StageUnavailable
                title="No practice scenario yet"
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
