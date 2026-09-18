import type { DesignResult } from "../lib/designs";

export type PracticeScenario = NonNullable<DesignResult["training_design"]>["practice_scenarios"][number];

/**
 * A fully opened view of one AWS-5 practice scenario: setup, learner role, fictional persona,
 * opening line, scripted turns, expected learner behaviors, facilitator cues, completion criteria,
 * rubric, and debrief. It is a script for a facilitator-led rehearsal. Nothing here runs a
 * simulation or scores a learner.
 */
export default function PracticeScript({
  scenario,
  behaviors,
  fixture,
}: {
  scenario: PracticeScenario;
  behaviors: { behavior_id: string; description: string }[];
  fixture: boolean;
}) {
  const behaviorText = (ids: string[] | undefined) =>
    (ids ?? [])
      .map((id) => behaviors.find((behavior) => behavior.behavior_id === id)?.description)
      .filter((text): text is string => Boolean(text));
  return (
    <article className="practice-card practice-script" aria-labelledby={`scenario-${scenario.scenario_id}`}>
      <div className="practice-head">
        <div>
          <span className="eyebrow">{fixture ? "Controlled non-AI practice specification" : "AI-generated practice specification"}</span>
          <h3 id={`scenario-${scenario.scenario_id}`}>{scenario.title}</h3>
          <p>{scenario.call_driver}</p>
        </div>
        <span>Learner role: {scenario.learner_role}</span>
      </div>

      <div className="persona-intro">
        <strong>{scenario.persona.name}</strong>
        <p>
          Fictional persona · {scenario.persona.context} · {scenario.persona.communication_style} ·{" "}
          {scenario.persona.emotional_state}
        </p>
        <blockquote>“{scenario.opening_line}”</blockquote>
      </div>

      <div className="script-grid">
        <div className="practice-objective">
          <span className="field-label">Scenario setup</span>
          <p>{scenario.scenario_setup ?? "No setup beyond the persona and opening line was supplied."}</p>
        </div>
        <div className="practice-objective">
          <span className="field-label">Learner objective</span>
          <p>{scenario.learner_objective}</p>
        </div>
        <div className="practice-objective">
          <span className="field-label">Target behaviors practiced</span>
          <ul>
            {behaviorText(scenario.behavior_ids).map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </div>
        {scenario.escalation_expectation !== undefined && (
          <div className="practice-objective">
            <span className="field-label">Escalation handling</span>
            <p>{scenario.escalation_expectation ?? "No escalation procedure was supplied, so none is scripted."}</p>
          </div>
        )}
      </div>

      <section className="script-section" aria-label="Persona guidance">
        <h4>Persona guidance for the facilitator</h4>
        <div className="practice-detail-grid">
          <p>
            <strong>Knows</strong>
            <br />
            {scenario.persona.knows}
          </p>
          <p>
            <strong>Wants</strong>
            <br />
            {scenario.persona.wants}
          </p>
          <p>
            <strong>Does not volunteer</strong>
            <br />
            {scenario.persona.withholding}
          </p>
          <p>
            <strong>If the learner succeeds</strong>
            <br />
            {scenario.persona.success_response}
          </p>
          <p>
            <strong>If the learner struggles</strong>
            <br />
            {scenario.persona.failure_response}
          </p>
        </div>
      </section>

      <section className="script-section" aria-label="Scripted turns">
        <h4>Scripted turns</h4>
        <ol className="script-turns">
          {scenario.beats.map((beat, index) => (
            <li key={beat.beat_id}>
              <span className="turn-number">Turn {index + 1}</span>
              <div>
                <strong>{beat.trigger}</strong>
                <p className="turn-line">Persona: “{beat.likely_response}”</p>
                <dl>
                  <div>
                    <dt>Expected learner behavior</dt>
                    <dd>{beat.expected_learner_behavior ?? "Not specified for this turn."}</dd>
                  </div>
                  <div>
                    <dt>If the learner succeeds</dt>
                    <dd>{beat.success_branch}</dd>
                  </div>
                  <div>
                    <dt>If the learner struggles</dt>
                    <dd>{beat.challenge_branch}</dd>
                  </div>
                  <div>
                    <dt>Facilitator cue</dt>
                    <dd>{beat.facilitator_cue ?? "No cue supplied."}</dd>
                  </div>
                </dl>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="script-section" aria-label="Completion criteria">
        <h4>Completion criteria</h4>
        <ul>
          {scenario.completion_criteria.map((criterion) => (
            <li key={criterion}>{criterion}</li>
          ))}
        </ul>
      </section>

      <div className="rubric-section">
        <span className="eyebrow">Practice rubric</span>
        <h4>Success looks like</h4>
        {scenario.rubric.map((item) => (
          <div className="rubric-item" key={item.criterion_id}>
            <strong>{item.practice_behavior}</strong>
            <p>{item.observable_success}</p>
            <p className="quiet">Scoring guidance: {item.scoring_guidance}</p>
          </div>
        ))}
        <h4>Debrief prompts</h4>
        <ul>
          {scenario.debrief_prompts.map((prompt) => (
            <li key={prompt}>{prompt}</li>
          ))}
        </ul>
        <p className="no-score">No learner has been scored. This script has not been run.</p>
      </div>
    </article>
  );
}
