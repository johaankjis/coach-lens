import type { InterventionRecord, InterventionType, SolutionAlignment } from "../lib/interventions";

const GATE = (type: InterventionType, outcome: SolutionAlignment | null): InterventionRecord["handoff"]["training_design_gate"] => {
  if (type !== "training" && type !== "practice_simulation") return "not_applicable";
  if (outcome === null) return "awaiting_solution_validation";
  return outcome === "aligned" ? "permitted" : "withheld";
};
const DECISION = (type: InterventionType): InterventionRecord["handoff"]["decision_type"] =>
  type === "training" || type === "practice_simulation" ? "training" : type === "investigate_further" ? "investigate" : "non_training";

export function interventionFixture(
  type: InterventionType = "training",
  outcome: SolutionAlignment | null = "aligned",
  options: { fixture?: boolean; humanRevised?: boolean; reviewStatus?: InterventionRecord["evidence_review_status"] } = {},
): InterventionRecord {
  const mode = options.fixture ? "controlled_fixture" : "provider";
  const provider = options.fixture ? { provider: "controlled fixture", model: null, generation_mode: mode } as const
    : { provider: "Amazon Bedrock", model: "global.anthropic.claude-sonnet-4-6", generation_mode: mode } as const;
  const status = outcome === null ? "intervention_proposed" : outcome === "aligned" ? "solution_validated" : "solution_questioned";
  return {
    hypothesis_id: "hyp_1", signal_id: "sig_1",
    validated_diagnosis: {
      hypothesis_id: "hyp_1", signal_id: "sig_1", approved_by: "supervisor-1", approved_at: "2026-09-17T12:00:00Z",
      human_revised: options.humanRevised ?? false,
      diagnosis: { observed_behavioral_defect: "One source QA result failed", cause_domain: options.humanRevised ? "process_gap" : "skill_gap",
        performance_dimension: options.humanRevised ? "undetermined" : "capability", explanation: "Validated explanation",
        supporting_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }], conflicting_evidence: [], missing_evidence: [] },
    },
    diagnosis_digest: "digest", evidence_review_status: options.reviewStatus ?? "not_reviewed", semantic_review: null,
    status,
    proposal: {
      intervention_id: "int_1", hypothesis_id: "hyp_1", signal_id: "sig_1", intervention_type: type,
      recommendation: "Rehearse the closing summary in short simulated calls.",
      rationale: "The validated skill gap is best closed by practice with feedback.",
      target_change: "State the next step and confirm member understanding before closing.",
      fit_to_cause: "Practice fits a capability skill gap; instruction alone would not.",
      evidence_reference_ids: ["EVID-001"], evidence_refs: [{ item_id: "ev_1", evaluation_id: "eval_1" }],
      limitations: ["Only two evaluations were available."], missing_evidence: ["Direct observation of a live call"],
      provider_reported_confidence: 0.6, provider_metadata: provider, created_at: "2026-09-17T12:10:00Z",
    },
    solution_validation: outcome === null ? null : {
      solution_validation_id: "sol_1", intervention_id: "int_1", hypothesis_id: "hyp_1", assessed: "proposed_intervention",
      alignment_outcome: outcome, solution_status: outcome === "aligned" ? "solution_validated" : "solution_questioned",
      alignment_assessment: outcome === "aligned" ? "Practice addresses the validated skill gap." : "Training does not address the validated cause.",
      aligned_points: outcome === "misaligned" ? [] : ["Type fits the validated cause"],
      misaligned_points: outcome === "misaligned" ? ["Agent training does not correct a process gap"] : [],
      unsupported_assumptions: outcome === "aligned" ? [] : ["Frequency alone implies a training need"],
      missing_information: outcome === "insufficient_evidence" ? ["What the agents were taught"] : [],
      provider_reported_confidence: 0.7, provider_metadata: provider, created_at: "2026-09-17T12:20:00Z",
    },
    handoff: {
      hypothesis_id: "hyp_1", intervention_id: "int_1", solution_validation_id: outcome === null ? null : "sol_1",
      intervention_type: type, decision_type: DECISION(type),
      solution_status: outcome === null ? null : outcome === "aligned" ? "solution_validated" : "solution_questioned",
      training_design_gate: GATE(type, outcome), human_reviewed_intervention: false,
    },
    created_at: "2026-09-17T12:10:00Z", updated_at: "2026-09-17T12:20:00Z",
  };
}
