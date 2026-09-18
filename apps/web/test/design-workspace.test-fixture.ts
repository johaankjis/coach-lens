import type { DesignResult } from "../lib/designs";

export function designFixture(kind: "training" | "non_training" | "investigate" = "training"): DesignResult {
  const run = "design_1";
  return {
    run_id: run, diagnosis_id: "hyp_1", generation_mode: "controlled_fixture",
    status: kind === "training" ? "ready_for_alignment_review" : kind === "non_training" ? "alternative_recommended" : "evidence_required",
    approved_diagnosis: { hypothesis_id: "hyp_1", signal_id: "sig_top", human_revised: false,
      diagnosis: { observed_behavioral_defect: "Missed clarity", cause_domain: "skill_gap", performance_dimension: "capability", explanation: "Human approved", supporting_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }], conflicting_evidence: [], missing_evidence: [] } },
    intervention: { run_id: run, diagnosis_id: "hyp_1", decision_type: kind,
      rationale: kind === "training" ? "Practice the resolution summary." : "Training is not supported by this evidence.",
      evidence_refs: [{ item_id: "ev_1", evaluation_id: "eval_1" }], risks: ["Limited sample"],
      unresolved_questions: kind === "investigate" ? ["Observe another call"] : [],
      next_actions: [{ action_id: `${run}/N1`, title: "Review next step", instructions: "Discuss with supervisor" }],
      provider_metadata: { provider: "test-fixture", model: null } },
    training_design: kind !== "training" ? null : {
      run_id: run, diagnosis_id: "hyp_1", performance_context: "Proposed response to validated clarity diagnosis",
      target_behaviors: [{ behavior_id: `${run}/B1`, diagnosis_id: "hyp_1", description: "State next step and check understanding" }],
      objectives: [{ objective_id: `${run}/O1`, behavior_ids: [`${run}/B1`], measurable_outcome: "Summarize and confirm on a simulated call" }],
      outline: [{ section_id: `${run}/S1`, title: "Model and rehearse", purpose: "Show and practice", duration_minutes: 12, objective_ids: [`${run}/O1`], activity_ids: [`${run}/A1`] }],
      activities: [{ activity_id: `${run}/A1`, activity_type: "guided_simulation", purpose: "Practice closure", instructions: "Respond to member", objective_ids: [`${run}/O1`], expected_learner_behavior: "Summarize and check", success_indicator: "Member confirms", duration_minutes: 12 }],
      decision_checks: [],
      practice_scenarios: [{ scenario_id: `${run}/P1`, title: "Follow-up call", call_driver: "Unclear resolution", learner_role: "Representative",
        persona: { persona_id: `${run}/PERSONA1`, name: "Morgan", context: "Synthetic member", communication_style: "Direct", emotional_state: "Concerned", knows: "Request exists", wants: "Next step", withholding: "Prior confusion", success_response: "Confirms", failure_response: "Repeats question" },
        learner_objective: "Confirm understanding", opening_line: "What happens next?", behavior_ids: [`${run}/B1`], objective_ids: [`${run}/O1`], activity_id: `${run}/A1`,
        beats: [{ beat_id: `${run}/BEAT1`, trigger: "Vague response", likely_response: "When?", success_branch: "Ask to confirm", challenge_branch: "Ask again" }],
        completion_criteria: ["Member confirms"], rubric: [{ criterion_id: `${run}/R1`, behavior_id: `${run}/B1`, objective_id: `${run}/O1`, practice_behavior: "Summarize and confirm", observable_success: "Clear next step and check", scoring_guidance: "Met if both occur" }], debrief_prompts: ["What was clear?"] }],
      provider_metadata: { provider: "test-fixture", model: null },
    },
  };
}
