import { label, shortId } from "../lib/diagnostics";
import type { DesignResult } from "../lib/designs";

// Every artifact below is an AI/fixture proposal. Nothing here is validated, aligned, or
// approved: the M3 approval covers the diagnosis only, and alignment review (M6) has not run.
export default function DesignWorkspace({ result }: { result: DesignResult }) {
  const decision = result.intervention;
  const design = result.training_design;
  const fixture = result.generation_mode === "controlled_fixture";
  const origin = fixture ? "Controlled non-AI fixture" : "AI-generated proposal";
  return (
    <section className="design-workspace" aria-label="Proposed intervention design">
      <div className="section-kicker">{fixture ? "CONTROLLED NON-AI DEMO PROPOSAL" : decision.decision_type === "training" ? "AI-GENERATED DESIGN PROPOSAL" : "AI-GENERATED INTERVENTION PROPOSAL"}</div>
      <h2>Proposed intervention: {label(decision.decision_type)}</h2>
      <p>{decision.rationale}</p>
      <p className="quiet">Validated diagnosis {shortId(result.diagnosis_id)} · {result.approved_diagnosis.human_revised ? "Human revision used" : "Approved original used"} · Evidence: {decision.evidence_refs.map((ref) => shortId(ref.item_id)).join(", ")} · {origin} ({decision.provider_metadata.provider}{decision.provider_metadata.model ? ` / ${decision.provider_metadata.model}` : ""}) · Not human-validated</p>
      {decision.risks.length > 0 && <><h3>Risks / limitations</h3><ul>{decision.risks.map((risk, i) => <li key={i}>{risk}</li>)}</ul></>}
      {decision.decision_type === "investigate" && <><h3>Additional evidence required</h3><p>Current evidence is insufficient to select an intervention. No training has been designed; the questions below must be answered first.</p></>}
      {decision.decision_type === "non_training" && <><h3>Training not selected</h3><p>The proposal is that a non-training action better addresses the validated diagnosis. No training outline, activities, practice, or rubric were generated.</p></>}
      {decision.unresolved_questions.length > 0 && <><h3>{decision.decision_type === "investigate" ? "Open questions" : "Unresolved questions"}</h3><ul>{decision.unresolved_questions.map((question, i) => <li key={i}>{question}</li>)}</ul></>}
      <h3>{design ? "Proposed next step" : "Proposed next actions"}</h3>
      <ul>{decision.next_actions.map((action) => <li key={action.action_id}><strong>{action.title}</strong> — {action.instructions}</li>)}</ul>
      {design && <>
        <div className="ready">READY FOR ALIGNMENT REVIEW <span>→</span></div>
        <p className="quiet">Proposed training design; not validated or alignment-reviewed. Structural references were checked; whether the design actually fits the diagnosis is an independent alignment review (M6). No learner has been scored.</p>
        <h3>Performance problem / design context</h3><p>{design.performance_context}</p>
        <h3>Target behaviors</h3><ul>{design.target_behaviors.map((b) => <li key={b.behavior_id}><strong>{shortId(b.behavior_id)}</strong> — {b.description}<div className="quiet">← Validated diagnosis {shortId(b.diagnosis_id)}</div></li>)}</ul>
        <h3>Objectives</h3><ul>{design.objectives.map((o) => <li key={o.objective_id}><strong>{shortId(o.objective_id)}</strong> — {o.measurable_outcome}<div className="quiet">← Target behavior {o.behavior_ids.map(shortId).join(", ")}</div></li>)}</ul>
        <h3>Training outline</h3><ol>{design.outline.map((s) => <li key={s.section_id}><strong>{s.title}</strong> ({s.duration_minutes} min) — {s.purpose}<div className="quiet">Objectives {s.objective_ids.map(shortId).join(", ")} · Activities {s.activity_ids.map(shortId).join(", ") || "none"}</div></li>)}</ol>
        <h3>Proposed activities</h3>{design.activities.map((a) => <section key={a.activity_id} className="design-card"><h4>{shortId(a.activity_id)} · {label(a.activity_type)}</h4><p>{a.purpose}</p><p><strong>Instructions:</strong> {a.instructions}</p><p><strong>Expected:</strong> {a.expected_learner_behavior}</p><p><strong>Success:</strong> {a.success_indicator} · {a.duration_minutes} min</p><p className="quiet">→ Objectives {a.objective_ids.map(shortId).join(", ")}</p></section>)}
        {design.decision_checks.length > 0 && <><h3>Decision checks</h3>{design.decision_checks.map((check) => <section key={check.check_id} className="design-card"><p>{check.situation}</p><h4>{check.question}</h4><ol>{check.options.map((option) => <li key={option.option_id}>{option.response} — {option.feedback}{option.correct && <strong> (intended correct response)</strong>}</li>)}</ol><p className="quiet">→ Objectives {check.objective_ids.map(shortId).join(", ")}</p></section>)}</>}
        <h3>Hands-on practice</h3>{design.practice_scenarios.map((scenario) => <section key={scenario.scenario_id} className="design-card"><h4>Proposed practice scenario: {scenario.title}</h4><p className="quiet">Simulation specification for a later interactive practice tool. Not run, not scored.</p><p><strong>Call driver:</strong> {scenario.call_driver}</p><p><strong>Learner role:</strong> {scenario.learner_role} · <strong>Objective:</strong> {scenario.learner_objective}</p><p><strong>Persona (synthetic):</strong> {scenario.persona.name} — {scenario.persona.context} {scenario.persona.communication_style} Tone: {scenario.persona.emotional_state}.</p><p><strong>Persona knows / wants:</strong> {scenario.persona.knows} / {scenario.persona.wants}</p><p><strong>Do not volunteer:</strong> {scenario.persona.withholding}</p><p><strong>If the learner succeeds:</strong> {scenario.persona.success_response} <strong>If the learner does not:</strong> {scenario.persona.failure_response}</p><p><strong>Opening line:</strong> “{scenario.opening_line}”</p><h4>Conversation beats</h4><ol>{scenario.beats.map((beat) => <li key={beat.beat_id}>{beat.trigger} Likely response: “{beat.likely_response}” If successful: {beat.success_branch} If challenged: {beat.challenge_branch}</li>)}</ol><p><strong>Completion:</strong> {scenario.completion_criteria.join(" ")}</p><h4>Practice rubric</h4><ul>{scenario.rubric.map((r) => <li key={r.criterion_id}><strong>{shortId(r.criterion_id)}</strong> — {r.practice_behavior} Success: {r.observable_success} Scoring: {r.scoring_guidance}<div className="quiet">→ Target behavior {shortId(r.behavior_id)} → Objective {shortId(r.objective_id)} ← Validated diagnosis</div></li>)}</ul><h4>Debrief</h4><ul>{scenario.debrief_prompts.map((prompt, i) => <li key={i}>{prompt}</li>)}</ul><p className="quiet">Scenario {shortId(scenario.scenario_id)} → Activity {shortId(scenario.activity_id)} · Behaviors {scenario.behavior_ids.map(shortId).join(", ")}</p></section>)}
        <p className="quiet">Design origin: {origin} ({design.provider_metadata.provider}{design.provider_metadata.model ? ` / ${design.provider_metadata.model}` : ""}). Awaiting independent alignment review.</p>
      </>}
    </section>
  );
}
