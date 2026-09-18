import type { Diagnosis, EvidenceReference } from "./diagnostics";

export type ProviderMetadata = { provider: string; model: string | null; generation_mode?: "provider" | "controlled_fixture" | null };

export type DesignResult = {
  run_id: string;
  diagnosis_id: string;
  generation_mode: "provider" | "controlled_fixture";
  status: "ready_for_alignment_review" | "alternative_recommended" | "evidence_required";
  approved_diagnosis: { hypothesis_id: string; signal_id: string; diagnosis: Diagnosis; human_revised: boolean };
  intervention: {
    run_id: string; diagnosis_id: string; decision_type: "training" | "non_training" | "investigate";
    // AWS-4 handoff fields; absent or null for the controlled M5 fixture. A provider-backed
    // training package only exists when the gate is "permitted" and the alignment "aligned".
    intervention_type?: string | null; recommendation?: string | null; target_change?: string | null;
    solution_alignment?: string | null; intervention_id?: string | null; solution_validation_id?: string | null;
    training_design_gate?: "awaiting_solution_validation" | "permitted" | "withheld" | "not_applicable" | null;
    rationale: string; evidence_refs: EvidenceReference[]; risks: string[]; unresolved_questions: string[];
    next_actions: { action_id: string; title: string; instructions: string }[];
    provider_metadata: ProviderMetadata;
  };
  training_design: null | {
    run_id: string; diagnosis_id: string; performance_context: string;
    target_behaviors: { behavior_id: string; diagnosis_id: string; description: string }[];
    objectives: { objective_id: string; behavior_ids: string[]; measurable_outcome: string; condition?: string | null; observable_action?: string | null; standard?: string | null }[];
    outline: { section_id: string; title: string; purpose: string; duration_minutes: number; objective_ids: string[]; activity_ids: string[] }[];
    activities: { activity_id: string; activity_type: string; purpose: string; instructions: string; objective_ids: string[]; expected_learner_behavior: string; success_indicator: string; duration_minutes: number }[];
    decision_checks: { check_id: string; objective_ids: string[]; behavior_ids?: string[]; situation: string; question: string; options: { option_id: string; response: string; feedback: string; correct: boolean }[] }[];
    practice_scenarios: { scenario_id: string; title: string; call_driver: string; learner_role: string; persona: { persona_id: string; name: string; context: string; communication_style: string; emotional_state: string; knows: string; wants: string; withholding: string; success_response: string; failure_response: string }; learner_objective: string; opening_line: string; behavior_ids: string[]; objective_ids: string[]; activity_id: string; beats: { beat_id: string; trigger: string; likely_response: string; success_branch: string; challenge_branch: string; expected_learner_behavior?: string | null; facilitator_cue?: string | null; behavior_ids?: string[] }[]; completion_criteria: string[]; rubric: { criterion_id: string; behavior_id: string; objective_id: string; practice_behavior: string; observable_success: string; scoring_guidance: string }[]; debrief_prompts: string[]; scenario_setup?: string | null; escalation_expectation?: string | null }[];
    // AWS-5: present when a provider-backed designer produced the package; absent for the fixture.
    design_basis?: DesignBasis | null;
    missing_operational_details?: MissingOperationalDetail[];
    provider_metadata: ProviderMetadata;
  };
  // AWS-5: mechanical gap -> intervention -> behavior -> objective -> activity -> practice -> rubric paths for AWS-6.
  alignment_trace?: AlignmentTrace | null;
};

export type DesignBasis = {
  gap: { diagnosis_id: string; signal_id: string; observed_behavior: string; cause_domain: string; performance_dimension: string; human_revised: boolean };
  // The AWS-4 intervention and solution review the package was generated from; every field is required so the
  // artifact traces back through the intervention and its solution validation to the human-validated diagnosis.
  intervention: {
    run_id: string; decision_type: "training"; intervention_type: "training" | "practice_simulation";
    intervention_id: string; solution_validation_id: string; solution_alignment: "aligned"; training_design_gate: "permitted";
    training_focus: "knowledge" | "skill" | "knowledge_and_skill"; validation_source: "aws4_solution_validator";
    summary: string; target_change: string;
  };
  guidance_version: string;
  supplied_operational_context: string[];
};

export type MissingOperationalDetail = { detail_id: string; placeholder: string; description: string; needed_for: string };

export type AlignmentTrace = {
  run_id: string; diagnosis_id: string; assessment: "structural_references_only";
  links: { diagnosis_id: string; intervention_run_id: string; behavior_id: string; objective_id: string; activity_id: string; scenario_id: string; criterion_id: string }[];
  knowledge_check_links: { check_id: string; objective_id: string; behavior_ids: string[] }[];
  missing_operational_detail_ids: string[];
};

const obj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const arr = (v: unknown, check: (x: unknown) => boolean): v is unknown[] => Array.isArray(v) && v.every(check);
const strings = (v: unknown) => arr(v, str);
const nonEmpty = (v: unknown, check: (x: unknown) => boolean): v is unknown[] => arr(v, check) && v.length > 0;
const metadata = (v: unknown): v is ProviderMetadata => obj(v) && str(v.provider) && (v.model === null || str(v.model));
const refs = (v: unknown) => arr(v, (x) => obj(x) && str(x.item_id) && (x.evaluation_id === null || str(x.evaluation_id)));
const action = (v: unknown) => obj(v) && str(v.action_id) && str(v.title) && str(v.instructions);
const behavior = (v: unknown) => obj(v) && str(v.behavior_id) && str(v.diagnosis_id) && str(v.description);
const objective = (v: unknown) => obj(v) && str(v.objective_id) && strings(v.behavior_ids) && str(v.measurable_outcome);
const activity = (v: unknown) => obj(v) && str(v.activity_id) && str(v.activity_type) && str(v.purpose) && str(v.instructions) && strings(v.objective_ids) && str(v.expected_learner_behavior) && str(v.success_indicator) && typeof v.duration_minutes === "number";
const section = (v: unknown) => obj(v) && str(v.section_id) && str(v.title) && str(v.purpose) && strings(v.objective_ids) && strings(v.activity_ids) && typeof v.duration_minutes === "number";
const check = (v: unknown) => obj(v) && str(v.check_id) && strings(v.objective_ids) && str(v.situation) && str(v.question) && arr(v.options, (x) => obj(x) && str(x.option_id) && str(x.response) && str(x.feedback) && typeof x.correct === "boolean") && v.options.length === 4 && v.options.filter((x) => (x as { correct: boolean }).correct).length === 1;
const persona = (v: unknown) => obj(v) && ["persona_id", "name", "context", "communication_style", "emotional_state", "knows", "wants", "withholding", "success_response", "failure_response"].every((key) => str(v[key]));
const beat = (v: unknown) => obj(v) && ["beat_id", "trigger", "likely_response", "success_branch", "challenge_branch"].every((key) => str(v[key]));
const rubric = (v: unknown) => obj(v) && ["criterion_id", "behavior_id", "objective_id", "practice_behavior", "observable_success", "scoring_guidance"].every((key) => str(v[key]));
const scenario = (v: unknown) => obj(v) && ["scenario_id", "title", "call_driver", "learner_role", "learner_objective", "opening_line", "activity_id"].every((key) => str(v[key])) && persona(v.persona) && nonEmpty(v.behavior_ids, str) && nonEmpty(v.objective_ids, str) && nonEmpty(v.beats, beat) && nonEmpty(v.completion_criteria, str) && nonEmpty(v.rubric, rubric) && nonEmpty(v.debrief_prompts, str);
const optionalText = (v: unknown) => v === undefined || v === null || str(v);
const basisIntervention = (v: unknown) => obj(v) && str(v.training_focus) && v.validation_source === "aws4_solution_validator" && str(v.summary) && str(v.target_change) && (v.intervention_type === "training" || v.intervention_type === "practice_simulation") && str(v.intervention_id) && str(v.solution_validation_id) && v.solution_alignment === "aligned" && v.training_design_gate === "permitted";
const basis = (v: unknown) => v === undefined || v === null || (obj(v) && obj(v.gap) && str(v.gap.observed_behavior) && str(v.gap.cause_domain) && basisIntervention(v.intervention) && str(v.guidance_version) && strings(v.supplied_operational_context));
const missingDetail = (v: unknown) => obj(v) && str(v.detail_id) && str(v.placeholder) && str(v.description) && str(v.needed_for);
const training = (v: unknown): v is NonNullable<DesignResult["training_design"]> => obj(v) && str(v.run_id) && str(v.diagnosis_id) && str(v.performance_context) && arr(v.target_behaviors, behavior) && v.target_behaviors.length > 0 && arr(v.objectives, objective) && v.objectives.length > 0 && arr(v.outline, section) && v.outline.length > 0 && arr(v.activities, activity) && v.activities.length > 0 && arr(v.decision_checks, check) && arr(v.practice_scenarios, scenario) && v.practice_scenarios.length > 0 && metadata(v.provider_metadata) && basis(v.design_basis) && (v.missing_operational_details === undefined || arr(v.missing_operational_details, missingDetail)) && v.practice_scenarios.every((s) => optionalText((s as Record<string, unknown>).scenario_setup) && optionalText((s as Record<string, unknown>).escalation_expectation));

export function isDesignResult(v: unknown): v is DesignResult {
  if (!obj(v) || !str(v.run_id) || !str(v.diagnosis_id) || (v.generation_mode !== "provider" && v.generation_mode !== "controlled_fixture") || !obj(v.approved_diagnosis) || !obj(v.intervention)) return false;
  const approved = v.approved_diagnosis;
  const decision = v.intervention;
  if (!str(approved.hypothesis_id) || approved.hypothesis_id !== v.diagnosis_id || !str(approved.signal_id) || !obj(approved.diagnosis) || typeof approved.human_revised !== "boolean") return false;
  if (!["observed_behavioral_defect", "cause_domain", "performance_dimension", "explanation"].every((key) => str((approved.diagnosis as Record<string, unknown>)[key])) || !refs(approved.diagnosis.supporting_evidence) || !refs(approved.diagnosis.conflicting_evidence) || !strings(approved.diagnosis.missing_evidence)) return false;
  if (!str(decision.run_id) || decision.run_id !== v.run_id || decision.diagnosis_id !== v.diagnosis_id || !str(decision.rationale) || !refs(decision.evidence_refs) || !strings(decision.risks) || !strings(decision.unresolved_questions) || !nonEmpty(decision.next_actions, action) || !metadata(decision.provider_metadata)) return false;
  for (const key of ["intervention_type", "recommendation", "target_change", "solution_alignment", "intervention_id", "solution_validation_id", "training_design_gate"])
    if (decision[key] !== undefined && decision[key] !== null && !str(decision[key])) return false;
  if (decision.decision_type === "training") return v.status === "ready_for_alignment_review" && training(v.training_design) && v.training_design.run_id === v.run_id && v.training_design.diagnosis_id === v.diagnosis_id;
  if (decision.decision_type === "non_training") return v.status === "alternative_recommended" && v.training_design === null;
  if (decision.decision_type === "investigate") return v.status === "evidence_required" && v.training_design === null && decision.unresolved_questions.length > 0;
  return false;
}

// AWS-6: one immutable semantic alignment review of a stored training package. It is an AI (or
// fixture) judgement, never a human decision; only an overall "aligned" verdict is design_aligned.
export const ALIGNMENT_OUTCOMES = ["aligned", "partially_aligned", "misaligned", "insufficient_information"] as const;
export type AlignmentOutcome = (typeof ALIGNMENT_OUTCOMES)[number];
export const ALIGNMENT_DIMENSIONS = ["gap_to_target_behavior", "target_behavior_to_objective", "objective_to_activity", "objective_to_knowledge_check", "target_behavior_to_practice", "practice_to_rubric", "intervention_to_package"] as const;
export type AlignmentDimension = (typeof ALIGNMENT_DIMENSIONS)[number];
export type DimensionReview = { outcome: AlignmentOutcome | "not_applicable"; assessment: string; misaligned_element_ids: string[] };
export type AlignmentReview = {
  alignment_review_id: string; run_id: string; diagnosis_id: string; intervention_id: string; solution_validation_id: string;
  design_digest: string; assessed: "training_design_package"; structural_trace: "structural_references_only";
  overall_outcome: AlignmentOutcome; design_status: "design_aligned" | "design_questioned"; overall_assessment: string;
  dimensions: Record<AlignmentDimension, DimensionReview>;
  misaligned_element_ids: string[]; unsupported_assumptions: string[]; missing_information: string[];
  provider_reported_confidence: number; provider_metadata: ProviderMetadata; created_at: string;
};

const dimensionReview = (v: unknown): v is DimensionReview => obj(v) && ([...ALIGNMENT_OUTCOMES, "not_applicable"] as string[]).includes(v.outcome as string) && str(v.assessment) && strings(v.misaligned_element_ids) && ((v.outcome === "aligned" || v.outcome === "not_applicable") ? (v.misaligned_element_ids as string[]).length === 0 : true);

export function isAlignmentReview(v: unknown): v is AlignmentReview {
  if (!obj(v) || !["alignment_review_id", "run_id", "diagnosis_id", "intervention_id", "solution_validation_id", "design_digest", "overall_assessment", "created_at"].every((key) => str(v[key]))) return false;
  if (v.assessed !== "training_design_package" || v.structural_trace !== "structural_references_only") return false;
  if (!ALIGNMENT_OUTCOMES.includes(v.overall_outcome as AlignmentOutcome)) return false;
  if (v.design_status !== (v.overall_outcome === "aligned" ? "design_aligned" : "design_questioned")) return false;
  if (!obj(v.dimensions) || !ALIGNMENT_DIMENSIONS.every((name) => dimensionReview((v.dimensions as Record<string, unknown>)[name]))) return false;
  if (!strings(v.misaligned_element_ids) || !strings(v.unsupported_assumptions) || !strings(v.missing_information)) return false;
  if (typeof v.provider_reported_confidence !== "number" || !Number.isFinite(v.provider_reported_confidence) || v.provider_reported_confidence < 0 || v.provider_reported_confidence > 1) return false;
  if (!metadata(v.provider_metadata)) return false;
  // An aligned verdict cannot name a misaligned element, an unsupported assumption, or a non-aligned dimension.
  if (v.overall_outcome === "aligned" && (v.misaligned_element_ids.length > 0 || v.unsupported_assumptions.length > 0 || v.missing_information.length > 0 || ALIGNMENT_DIMENSIONS.some((name) => !["aligned", "not_applicable"].includes((v.dimensions as Record<string, DimensionReview>)[name].outcome)))) return false;
  return true;
}
