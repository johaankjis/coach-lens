import AlignmentCheck from "./alignment-check";
import { label } from "../lib/diagnostics";
import type { AlignmentReview, DesignResult, ProviderMetadata } from "../lib/designs";

const origin = (fixture: boolean, meta: ProviderMetadata) =>
  `Design origin: ${fixture ? "Controlled non-AI fixture" : "AI-generated proposal"} (${meta.provider}${meta.model ? ` / ${meta.model}` : ""})`;

function Trace({ result }: { result: DesignResult }) {
  const d = result.training_design;
  const decision = result.intervention;
  const diagnosis = result.approved_diagnosis;
  return (
    <details className="design-trace">
      <summary>View trace, evidence &amp; provenance</summary>
      <div className="trace-content">
        <p>
          Source QA evidence → observed signal →{" "}
          {diagnosis.human_revised
            ? "human-revised"
            : "reviewer-approved original"}{" "}
          working diagnosis → proposed intervention
          {d
            ? " → target behavior → objective → activity → practice → rubric"
            : ""}
          .
        </p>
        <dl>
          <div>
            <dt>Observed signal ID</dt>
            <dd>{diagnosis.signal_id}</dd>
          </div>
          <div>
            <dt>Validated diagnosis ID</dt>
            <dd>{diagnosis.hypothesis_id}</dd>
          </div>
          <div>
            <dt>Design run ID</dt>
            <dd>{result.run_id}</dd>
          </div>
          <div>
            <dt>Intervention evidence</dt>
            <dd>
              {decision.evidence_refs
                .map(
                  (r) =>
                    `${r.item_id}${r.evaluation_id ? ` / ${r.evaluation_id}` : ""}`,
                )
                .join("; ")}
            </dd>
          </div>
          <div>
            <dt>Diagnostic supporting evidence</dt>
            <dd>
              {diagnosis.diagnosis.supporting_evidence
                .map((r) => r.item_id)
                .join("; ") || "None cited"}
            </dd>
          </div>
          <div>
            <dt>Diagnostic conflicting evidence</dt>
            <dd>
              {diagnosis.diagnosis.conflicting_evidence
                .map((r) => r.item_id)
                .join("; ") || "None cited"}
            </dd>
          </div>
          {decision.intervention_id && (
            <div>
              <dt>Intervention record</dt>
              <dd>
                {decision.intervention_id}
                {decision.solution_validation_id
                  ? ` → solution review ${decision.solution_validation_id}`
                  : ""}
              </dd>
            </div>
          )}
          <div>
            <dt>Decision provider</dt>
            <dd>
              {decision.provider_metadata.provider}
              {decision.provider_metadata.model &&
                ` / ${decision.provider_metadata.model}`}
            </dd>
          </div>
          {d && (
            <div>
              <dt>Design context</dt>
              <dd>{d.performance_context}</dd>
            </div>
          )}
          {d && (
            <div>
              <dt>Training provider</dt>
              <dd>
                {d.provider_metadata.provider}
                {d.provider_metadata.model && ` / ${d.provider_metadata.model}`}
              </dd>
            </div>
          )}
        </dl>
        {d && (
          <>
            <h4>Artifact references</h4>
            <ul className="trace-references">
              {d.target_behaviors.map((b) => (
                <li key={b.behavior_id}>
                  Behavior {b.behavior_id} ← diagnosis {b.diagnosis_id}
                </li>
              ))}
              {d.objectives.map((o) => (
                <li key={o.objective_id}>
                  Objective {o.objective_id} ← behavior{" "}
                  {o.behavior_ids.join(", ")}
                </li>
              ))}
              {d.outline.map((s) => (
                <li key={s.section_id}>
                  Section {s.section_id} → objectives{" "}
                  {s.objective_ids.join(", ")} → activities{" "}
                  {s.activity_ids.join(", ") || "none"}
                </li>
              ))}
              {d.activities.map((a) => (
                <li key={a.activity_id}>
                  Activity {a.activity_id} ← objectives{" "}
                  {a.objective_ids.join(", ")}
                </li>
              ))}
              {d.decision_checks.map((c) => (
                <li key={c.check_id}>
                  Decision check {c.check_id} ← objectives{" "}
                  {c.objective_ids.join(", ")}; options{" "}
                  {c.options.map((o) => o.option_id).join(", ")}
                </li>
              ))}
              {d.practice_scenarios.map((s) => (
                <li key={s.scenario_id}>
                  Practice {s.scenario_id} ← activity {s.activity_id}; behaviors{" "}
                  {s.behavior_ids.join(", ")}; objectives{" "}
                  {s.objective_ids.join(", ")}; persona {s.persona.persona_id};
                  beats {s.beats.map((b) => b.beat_id).join(", ")}; rubric{" "}
                  {s.rubric
                    .map(
                      (r) =>
                        `${r.criterion_id} → ${r.behavior_id} / ${r.objective_id}`,
                    )
                    .join(", ")}
                </li>
              ))}
            </ul>
          </>
        )}
        <p>
          Structural references were checked; whether the design actually fits
          the diagnosis is an independent alignment review (M6).
        </p>
        <p>The intervention proposal has not been human validated.</p>
      </div>
    </details>
  );
}

export default function DesignWorkspace({
  result,
  signalLabel,
  alignmentReview = null,
  onCheckAlignment,
  checkingAlignment = false,
  alignmentDisabled = false,
}: {
  result: DesignResult;
  signalLabel?: string;
  // AWS-6: the stored semantic review of this run, when one exists, and the action to request one.
  alignmentReview?: AlignmentReview | null;
  onCheckAlignment?: () => void;
  checkingAlignment?: boolean;
  alignmentDisabled?: boolean;
}) {
  const decision = result.intervention;
  const d = result.training_design;
  const fixture = result.generation_mode === "controlled_fixture";
  const diagnosis = result.approved_diagnosis.diagnosis;
  const minutes = d?.outline.reduce((sum, s) => sum + s.duration_minutes, 0);
  const review = d && alignmentReview?.run_id === result.run_id ? alignmentReview : null;
  const reviewStatus = review ? (review.design_status === "design_aligned" ? "DESIGN ALIGNED" : "DESIGN QUESTIONED") : null;
  return (
    <section
      className="design-workspace"
      aria-label="Proposed intervention design"
    >
      <header className="design-hero">
        <span className="section-kicker">
          {fixture
            ? "CONTROLLED NON-AI DEMO PROPOSAL"
            : "AI-GENERATED INTERVENTION PROPOSAL"}
        </span>
        <div className="design-status" role="status">
          {d
            ? reviewStatus ?? "READY FOR ALIGNMENT REVIEW"
            : decision.decision_type === "non_training"
              ? "TRAINING NOT SELECTED"
              : "MORE EVIDENCE NEEDED"}
        </div>
        <h2>
          {d
            ? "Targeted learning intervention"
            : decision.decision_type === "non_training"
              ? "Operational intervention proposed"
              : "Investigate before selecting an intervention"}
        </h2>
        <p className="design-problem">
          {signalLabel ?? diagnosis.observed_behavioral_defect}
        </p>
        {signalLabel && (
          <p className="design-observation">
            {diagnosis.observed_behavioral_defect}
          </p>
        )}
        <div className="design-summary-meta">
          <span>
            Working diagnosis: {label(diagnosis.cause_domain)} ·{" "}
            {label(diagnosis.performance_dimension)} <b>Human validated</b>
          </span>
          {decision.intervention_type && (
            <span>
              Solution-reviewed intervention: {label(decision.intervention_type)}
              {decision.solution_alignment
                ? ` · solution review ${label(decision.solution_alignment)}`
                : ""}{" "}
              <b>Not human validated</b>
            </span>
          )}
          {d && <span>{minutes} min learning plan</span>}
        </div>
        <p className="design-status-note">
          {d
            ? review
              ? review.design_status === "design_aligned"
                ? "Proposed training design; the independent alignment review found it addresses the confirmed gap. Not deployed, no outcome measured, no learner scored."
                : "Proposed training design; the independent alignment review questioned it. Not deployed, no outcome measured, no learner scored."
              : "Proposed training design; awaiting independent alignment review. No learner has been scored."
            : decision.decision_type === "non_training"
              ? "No training outline, activities, practice, or rubric were generated."
              : "Current evidence is insufficient to select an intervention. No training has been designed."}
        </p>
        <p className="design-origin">
          {origin(fixture, decision.provider_metadata)}
        </p>
      </header>
      <section className="design-section">
        <span className="eyebrow">Why this {d ? "training" : "decision"}?</span>
        <h3>Intervention rationale</h3>
        <p>{decision.rationale}</p>
      </section>
      {d?.design_basis && (
        <section className="design-section design-basis">
          <span className="eyebrow">Design basis</span>
          <h3>What this package was designed from</h3>
          <dl>
            <div>
              <dt>Confirmed gap</dt>
              <dd>{d.design_basis.gap.observed_behavior}</dd>
            </div>
            <div>
              <dt>Validated intervention</dt>
              <dd>
                {label(d.design_basis.intervention.training_focus)} focus ·{" "}
                {label(d.design_basis.intervention.intervention_type)} · solution-validated by the
                AWS-4 review ({d.design_basis.intervention.intervention_id} →{" "}
                {d.design_basis.intervention.solution_validation_id})
              </dd>
            </div>
            <div>
              <dt>Target change</dt>
              <dd>{d.design_basis.intervention.target_change}</dd>
            </div>
            <div>
              <dt>Design guidance</dt>
              <dd>{d.design_basis.guidance_version}</dd>
            </div>
            <div>
              <dt>Operational context supplied</dt>
              <dd>
                {d.design_basis.supplied_operational_context.length > 0
                  ? d.design_basis.supplied_operational_context.join("; ")
                  : "None. Any operational detail the design needed is listed as missing below, not invented."}
              </dd>
            </div>
          </dl>
        </section>
      )}
      {d && (d.missing_operational_details?.length ?? 0) > 0 && (
        <section className="design-section missing-details">
          <span className="eyebrow">Operational details still needed</span>
          <h3>Placeholders the designer did not fill in</h3>
          <ul>
            {d.missing_operational_details!.map((m) => (
              <li key={m.detail_id}>
                <strong>{m.placeholder}</strong>
                <p>{m.description}</p>
                <p className="quiet">Needed for: {m.needed_for}</p>
              </li>
            ))}
          </ul>
        </section>
      )}
      {d && (
        <>
          <section className="design-section target-section">
            <span className="eyebrow">Target behavior</span>
            <h3>What the learner needs to do</h3>
            {d.target_behaviors.map((b) => (
              <p className="target-statement" key={b.behavior_id}>
                {b.description}
              </p>
            ))}
          </section>
          <section className="design-section">
            <span className="eyebrow">Objectives</span>
            <h3>What the learner should demonstrate</h3>
            <ul className="objective-list">
              {d.objectives.map((o) => (
                <li key={o.objective_id}>
                  {o.measurable_outcome}
                  {o.standard && (
                    <p className="quiet objective-standard">Standard: {o.standard}</p>
                  )}
                </li>
              ))}
            </ul>
          </section>
          <section className="design-section">
            <span className="eyebrow">Training outline</span>
            <h3>Learning plan</h3>
            <ol className="learning-plan">
              {d.outline.map((s, i) => (
                <li key={s.section_id}>
                  <span className="plan-number">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h4>{s.title}</h4>
                    <p>{s.purpose}</p>
                    {s.activity_ids.map((id) => {
                      const a = d.activities.find(
                        (item) => item.activity_id === id,
                      );
                      return (
                        a && (
                          <div className="plan-activity" key={id}>
                            <span>{label(a.activity_type)}</span>
                            <strong>{a.purpose}</strong>
                            <p>{a.instructions}</p>
                          </div>
                        )
                      );
                    })}
                  </div>
                  <span className="plan-duration">
                    {s.duration_minutes} min
                  </span>
                </li>
              ))}
            </ol>
          </section>
          <section className="design-section">
            <span className="eyebrow">Proposed activities</span>
            <h3>What the learner will do</h3>
            {d.activities.map((a) => (
              <article
                key={a.activity_id}
                className="design-card activity-card"
              >
                <div className="activity-heading">
                  <span>{label(a.activity_type)}</span>
                  <span>{a.duration_minutes} min</span>
                </div>
                <h4>{a.purpose}</h4>
                <dl>
                  <div>
                    <dt>Instructions</dt>
                    <dd>{a.instructions}</dd>
                  </div>
                  <div>
                    <dt>Expected behavior</dt>
                    <dd>{a.expected_learner_behavior}</dd>
                  </div>
                  <div>
                    <dt>Success indicator</dt>
                    <dd>{a.success_indicator}</dd>
                  </div>
                </dl>
              </article>
            ))}
          </section>
          {d.decision_checks.length > 0 && (
            <section className="design-section">
              <span className="eyebrow">
                Design preview · not a learner assessment
              </span>
              <h3>Decision checks</h3>
              {d.decision_checks.map((c) => (
                <article
                  key={c.check_id}
                  className="design-card decision-check"
                >
                  <p className="quiet">{c.situation}</p>
                  <h4>{c.question}</h4>
                  <ol>
                    {c.options.map((o) => (
                      <li key={o.option_id}>
                        <span>{o.response}</span>
                        {o.correct && (
                          <strong className="correct-label">
                            (intended correct response)
                          </strong>
                        )}
                        <p>Feedback: {o.feedback}</p>
                      </li>
                    ))}
                  </ol>
                </article>
              ))}
            </section>
          )}
          <section className="design-section">
            <span className="eyebrow">Hands-on practice</span>
            <h3>The practice CoachLens proposed</h3>
            {d.practice_scenarios.map((s) => (
              <article key={s.scenario_id} className="practice-card">
                <div className="practice-head">
                  <div>
                    <span className="eyebrow">
                      Proposed simulation specification
                    </span>
                    <h4>{s.title}</h4>
                    <p>{s.call_driver}</p>
                  </div>
                  <span>{s.learner_role}</span>
                </div>
                <div className="persona-intro">
                  <strong>{s.persona.name}</strong>
                  <p>
                    {s.persona.context} · {s.persona.communication_style} ·{" "}
                    {s.persona.emotional_state}
                  </p>
                  <blockquote>“{s.opening_line}”</blockquote>
                </div>
                <div className="practice-objective">
                  <span className="field-label">Learner objective</span>
                  <p>{s.learner_objective}</p>
                </div>
                {s.scenario_setup && (
                  <div className="practice-objective">
                    <span className="field-label">Scenario setup</span>
                    <p>{s.scenario_setup}</p>
                  </div>
                )}
                {s.escalation_expectation !== undefined && (
                  <div className="practice-objective">
                    <span className="field-label">Escalation handling</span>
                    <p>
                      {s.escalation_expectation ??
                        "No escalation procedure was supplied, so none is scripted."}
                    </p>
                  </div>
                )}
                <details className="practice-details">
                  <summary>
                    View scenario guidance and conversation beats
                  </summary>
                  <div className="practice-detail-grid">
                    <p>
                      <strong>Persona knows</strong>
                      <br />
                      {s.persona.knows}
                    </p>
                    <p>
                      <strong>Persona wants</strong>
                      <br />
                      {s.persona.wants}
                    </p>
                    <p>
                      <strong>Does not volunteer</strong>
                      <br />
                      {s.persona.withholding}
                    </p>
                    <p>
                      <strong>If learner succeeds</strong>
                      <br />
                      {s.persona.success_response}
                    </p>
                    <p>
                      <strong>If learner struggles</strong>
                      <br />
                      {s.persona.failure_response}
                    </p>
                  </div>
                  <h5>Conversation beats</h5>
                  <ol>
                    {s.beats.map((b) => (
                      <li key={b.beat_id}>
                        <strong>{b.trigger}</strong>
                        <p>Likely response: “{b.likely_response}”</p>
                        {b.expected_learner_behavior && (
                          <p>Expected learner behavior: {b.expected_learner_behavior}</p>
                        )}
                        <p>Success: {b.success_branch}</p>
                        <p>Challenge: {b.challenge_branch}</p>
                        {b.facilitator_cue && (
                          <p className="quiet">Facilitator cue: {b.facilitator_cue}</p>
                        )}
                      </li>
                    ))}
                  </ol>
                  <h5>Completion criteria</h5>
                  <ul>
                    {s.completion_criteria.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                  <h5>Debrief prompts</h5>
                  <ul>
                    {s.debrief_prompts.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </details>
                <div className="rubric-section">
                  <span className="eyebrow">Practice rubric</span>
                  <h5>Success looks like</h5>
                  {s.rubric.map((r) => (
                    <div className="rubric-item" key={r.criterion_id}>
                      <strong>{r.practice_behavior}</strong>
                      <p>{r.observable_success}</p>
                      <p className="quiet">
                        Scoring guidance: {r.scoring_guidance}
                      </p>
                    </div>
                  ))}
                  <p className="no-score">No learner has been scored.</p>
                </div>
              </article>
            ))}
          </section>
        </>
      )}
      {d && !review && onCheckAlignment && (
        <section className="design-section alignment-check pending">
          <span className="eyebrow">Alignment Check</span>
          <h3>AI semantic design review</h3>
          <p className="alignment-scope">
            The AWS-5 structural trace only proves the references above are consistent. Check Alignment asks an
            independent reviewer whether the target behavior, objectives, activities, knowledge check, practice, and
            rubric actually address the confirmed gap and the validated intervention. It does not change the package.
          </p>
          <button type="button" className="button primary" disabled={checkingAlignment || alignmentDisabled} onClick={onCheckAlignment}>
            CHECK ALIGNMENT
          </button>
          {checkingAlignment && <p role="status">Reviewing design alignment…</p>}
        </section>
      )}
      {review && <AlignmentCheck review={review} />}
      <section className="design-section next-actions">
        <span className="eyebrow">
          {d ? "Next review step" : "Recommended next action"}
        </span>
        <h3>Proposed next actions</h3>
        <ul>
          {decision.next_actions.map((a) => (
            <li key={a.action_id}>
              <strong>{a.title}</strong>
              <p>{a.instructions}</p>
            </li>
          ))}
        </ul>
      </section>
      {decision.risks.length > 0 && (
        <section className="design-section">
          <span className="eyebrow">Decision limits</span>
          <h3>Risks / limitations</h3>
          <ul>
            {decision.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </section>
      )}
      {decision.unresolved_questions.length > 0 && (
        <section className="design-section">
          <span className="eyebrow">Evidence still needed</span>
          <h3>Unresolved questions</h3>
          <ul>
            {decision.unresolved_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </section>
      )}
      <Trace result={result} />
    </section>
  );
}
