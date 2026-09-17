import type { Diagnosis, EvidenceReference } from "./diagnostics";

export type DesignResult = {
  run_id: string;
  diagnosis_id: string;
  generation_mode: "provider" | "controlled_fixture";
  status: "ready_for_alignment_review" | "alternative_recommended" | "evidence_required";
  approved_diagnosis: { hypothesis_id: string; signal_id: string; diagnosis: Diagnosis; human_revised: boolean };
  intervention: {
    run_id: string; diagnosis_id: string; decision_type: "training" | "non_training" | "investigate";
    rationale: string; evidence_refs: EvidenceReference[]; risks: string[]; unresolved_questions: string[];
    next_actions: { action_id: string; title: string; instructions: string }[];
  };
  training_design: null | {
    run_id: string; diagnosis_id: string; performance_context: string;
    target_behaviors: { behavior_id: string; diagnosis_id: string; description: string }[];
    objectives: { objective_id: string; behavior_ids: string[]; measurable_outcome: string }[];
    outline: { section_id: string; title: string; purpose: string; duration_minutes: number; objective_ids: string[]; activity_ids: string[] }[];
    activities: { activity_id: string; activity_type: string; purpose: string; instructions: string; objective_ids: string[]; expected_learner_behavior: string; success_indicator: string; duration_minutes: number }[];
    decision_checks: { check_id: string; objective_ids: string[]; situation: string; question: string; options: { option_id: string; response: string; feedback: string; correct: boolean }[] }[];
    practice_scenarios: { scenario_id: string; title: string; call_driver: string; learner_role: string; persona: { persona_id: string; name: string; context: string; communication_style: string; emotional_state: string; knows: string; wants: string; withholding: string; success_response: string; failure_response: string }; learner_objective: string; opening_line: string; behavior_ids: string[]; objective_ids: string[]; activity_id: string; beats: { beat_id: string; trigger: string; likely_response: string; success_branch: string; challenge_branch: string }[]; completion_criteria: string[]; rubric: { criterion_id: string; behavior_id: string; objective_id: string; practice_behavior: string; observable_success: string; scoring_guidance: string }[]; debrief_prompts: string[] }[];
  };
};

const obj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const arr = (v: unknown, check: (x: unknown) => boolean): v is unknown[] => Array.isArray(v) && v.every(check);
const strings = (v: unknown) => arr(v, str);
const refs = (v: unknown) => arr(v, (x) => obj(x) && str(x.item_id) && (x.evaluation_id === null || str(x.evaluation_id)));
const action = (v: unknown) => obj(v) && str(v.action_id) && str(v.title) && str(v.instructions);
const behavior = (v: unknown) => obj(v) && str(v.behavior_id) && str(v.diagnosis_id) && str(v.description);
const objective = (v: unknown) => obj(v) && str(v.objective_id) && strings(v.behavior_ids) && str(v.measurable_outcome);
const activity = (v: unknown) => obj(v) && str(v.activity_id) && str(v.activity_type) && str(v.purpose) && str(v.instructions) && strings(v.objective_ids) && str(v.expected_learner_behavior) && str(v.success_indicator) && typeof v.duration_minutes === "number";
const section = (v: unknown) => obj(v) && str(v.section_id) && str(v.title) && str(v.purpose) && strings(v.objective_ids) && strings(v.activity_ids) && typeof v.duration_minutes === "number";
const check = (v: unknown) => obj(v) && str(v.check_id) && strings(v.objective_ids) && str(v.situation) && str(v.question) && arr(v.options, (x) => obj(x) && str(x.option_id) && str(x.response) && str(x.feedback) && typeof x.correct === "boolean");
const persona = (v: unknown) => obj(v) && ["persona_id", "name", "context", "communication_style", "emotional_state", "knows", "wants", "withholding", "success_response", "failure_response"].every((key) => str(v[key]));
const beat = (v: unknown) => obj(v) && ["beat_id", "trigger", "likely_response", "success_branch", "challenge_branch"].every((key) => str(v[key]));
const rubric = (v: unknown) => obj(v) && ["criterion_id", "behavior_id", "objective_id", "practice_behavior", "observable_success", "scoring_guidance"].every((key) => str(v[key]));
const scenario = (v: unknown) => obj(v) && ["scenario_id", "title", "call_driver", "learner_role", "learner_objective", "opening_line", "activity_id"].every((key) => str(v[key])) && persona(v.persona) && strings(v.behavior_ids) && strings(v.objective_ids) && arr(v.beats, beat) && strings(v.completion_criteria) && arr(v.rubric, rubric) && strings(v.debrief_prompts);
const training = (v: unknown): v is NonNullable<DesignResult["training_design"]> => obj(v) && str(v.run_id) && str(v.diagnosis_id) && str(v.performance_context) && arr(v.target_behaviors, behavior) && v.target_behaviors.length > 0 && arr(v.objectives, objective) && v.objectives.length > 0 && arr(v.outline, section) && v.outline.length > 0 && arr(v.activities, activity) && v.activities.length > 0 && arr(v.decision_checks, check) && arr(v.practice_scenarios, scenario) && v.practice_scenarios.length > 0;

export function isDesignResult(v: unknown): v is DesignResult {
  if (!obj(v) || !str(v.run_id) || !str(v.diagnosis_id) || (v.generation_mode !== "provider" && v.generation_mode !== "controlled_fixture") || !obj(v.approved_diagnosis) || !obj(v.intervention)) return false;
  const approved = v.approved_diagnosis;
  const decision = v.intervention;
  if (!str(approved.hypothesis_id) || approved.hypothesis_id !== v.diagnosis_id || !str(approved.signal_id) || !obj(approved.diagnosis) || typeof approved.human_revised !== "boolean") return false;
  if (!["observed_behavioral_defect", "cause_domain", "performance_dimension", "explanation"].every((key) => str((approved.diagnosis as Record<string, unknown>)[key])) || !refs(approved.diagnosis.supporting_evidence) || !refs(approved.diagnosis.conflicting_evidence) || !strings(approved.diagnosis.missing_evidence)) return false;
  if (!str(decision.run_id) || decision.run_id !== v.run_id || decision.diagnosis_id !== v.diagnosis_id || !str(decision.rationale) || !refs(decision.evidence_refs) || !strings(decision.risks) || !strings(decision.unresolved_questions) || !arr(decision.next_actions, action)) return false;
  if (decision.decision_type === "training") return v.status === "ready_for_alignment_review" && training(v.training_design) && v.training_design.run_id === v.run_id && v.training_design.diagnosis_id === v.diagnosis_id;
  if (decision.decision_type === "non_training") return v.status === "alternative_recommended" && v.training_design === null;
  if (decision.decision_type === "investigate") return v.status === "evidence_required" && v.training_design === null;
  return false;
}
