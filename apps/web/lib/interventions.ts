import type { Diagnosis, EvidenceReference } from "./diagnostics";

/** AWS-4 record. Neither stage is a human decision; the human decision is the diagnosis approval. */
export const INTERVENTION_TYPES = ["training", "practice_simulation", "coaching", "process_correction", "investigate_further"] as const;
export type InterventionType = (typeof INTERVENTION_TYPES)[number];
export const ALIGNMENTS = ["aligned", "partially_aligned", "misaligned", "insufficient_evidence"] as const;
export type SolutionAlignment = (typeof ALIGNMENTS)[number];
export type TrainingDesignGate = "awaiting_solution_validation" | "permitted" | "withheld" | "not_applicable";
export type EvidenceReviewStatus = "evidence_validated" | "evidence_questioned" | "not_reviewed" | "original_proposal_only";

export type ProviderMetadata = { provider: string; model: string | null; generation_mode?: "provider" | "controlled_fixture" | null };

export type InterventionProposal = {
  intervention_id: string; hypothesis_id: string; signal_id: string;
  intervention_type: InterventionType; recommendation: string; rationale: string;
  target_change: string; fit_to_cause: string;
  evidence_reference_ids: string[]; evidence_refs: EvidenceReference[];
  limitations: string[]; missing_evidence: string[];
  provider_reported_confidence: number; provider_metadata: ProviderMetadata; created_at: string;
};

export type SolutionValidation = {
  solution_validation_id: string; intervention_id: string; hypothesis_id: string;
  assessed: "proposed_intervention"; alignment_outcome: SolutionAlignment;
  solution_status: "solution_validated" | "solution_questioned"; alignment_assessment: string;
  aligned_points: string[]; misaligned_points: string[]; unsupported_assumptions: string[];
  missing_information: string[]; provider_reported_confidence: number;
  provider_metadata: ProviderMetadata; created_at: string;
};

export type InterventionRecord = {
  hypothesis_id: string; signal_id: string;
  validated_diagnosis: { hypothesis_id: string; signal_id: string; diagnosis: Diagnosis; approved_by: string; approved_at: string; human_revised: boolean };
  diagnosis_digest: string; evidence_review_status: EvidenceReviewStatus;
  semantic_review: { validation_id: string; validation_outcome: string; semantic_status: "evidence_validated" | "evidence_questioned"; assessed_proposal: "provider_hypothesis"; describes_validated_diagnosis: boolean } | null;
  status: "intervention_proposed" | "solution_validated" | "solution_questioned";
  proposal: InterventionProposal; solution_validation: SolutionValidation | null;
  handoff: { hypothesis_id: string; intervention_id: string; solution_validation_id: string | null; intervention_type: InterventionType; decision_type: "training" | "non_training" | "investigate"; solution_status: "solution_validated" | "solution_questioned" | null; training_design_gate: TrainingDesignGate; human_reviewed_intervention: false };
  created_at: string; updated_at: string;
};

const obj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");
const refs = (v: unknown): v is EvidenceReference[] => Array.isArray(v) && v.every((x) => obj(x) && str(x.item_id) && (x.evaluation_id === null || str(x.evaluation_id)));
const metadata = (v: unknown): v is ProviderMetadata => obj(v) && str(v.provider) && (v.model === null || v.model === undefined || str(v.model));
const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const diagnosis = (v: unknown): v is Diagnosis => obj(v) && ["observed_behavioral_defect", "cause_domain", "performance_dimension", "explanation"].every((key) => str(v[key])) && refs(v.supporting_evidence) && refs(v.conflicting_evidence) && strings(v.missing_evidence);

function proposal(v: unknown): v is InterventionProposal {
  return obj(v) && str(v.intervention_id) && str(v.hypothesis_id) && str(v.signal_id) &&
    INTERVENTION_TYPES.includes(v.intervention_type as InterventionType) &&
    ["recommendation", "rationale", "target_change", "fit_to_cause", "created_at"].every((key) => str(v[key])) &&
    strings(v.evidence_reference_ids) && refs(v.evidence_refs) && strings(v.limitations) && strings(v.missing_evidence) &&
    number(v.provider_reported_confidence) && metadata(v.provider_metadata);
}
function validation(v: unknown): v is SolutionValidation {
  return obj(v) && str(v.solution_validation_id) && str(v.intervention_id) && str(v.hypothesis_id) &&
    v.assessed === "proposed_intervention" && ALIGNMENTS.includes(v.alignment_outcome as SolutionAlignment) &&
    (v.solution_status === "solution_validated" || v.solution_status === "solution_questioned") &&
    (v.solution_status === "solution_validated") === (v.alignment_outcome === "aligned") &&
    str(v.alignment_assessment) && str(v.created_at) &&
    ["aligned_points", "misaligned_points", "unsupported_assumptions", "missing_information"].every((key) => strings(v[key])) &&
    number(v.provider_reported_confidence) && metadata(v.provider_metadata);
}

export function isInterventionRecord(v: unknown): v is InterventionRecord {
  if (!obj(v) || !str(v.hypothesis_id) || !str(v.signal_id) || !str(v.diagnosis_digest) || !str(v.created_at) || !str(v.updated_at)) return false;
  if (!["evidence_validated", "evidence_questioned", "not_reviewed", "original_proposal_only"].includes(v.evidence_review_status as string)) return false;
  const approved = v.validated_diagnosis;
  if (!obj(approved) || approved.hypothesis_id !== v.hypothesis_id || approved.signal_id !== v.signal_id || !diagnosis(approved.diagnosis) || !str(approved.approved_by) || !str(approved.approved_at) || typeof approved.human_revised !== "boolean") return false;
  if (v.semantic_review !== null && !(obj(v.semantic_review) && str(v.semantic_review.validation_id) && str(v.semantic_review.validation_outcome) && (v.semantic_review.semantic_status === "evidence_validated" || v.semantic_review.semantic_status === "evidence_questioned") && v.semantic_review.assessed_proposal === "provider_hypothesis" && typeof v.semantic_review.describes_validated_diagnosis === "boolean")) return false;
  if (!proposal(v.proposal) || v.proposal.hypothesis_id !== v.hypothesis_id) return false;
  const handoff = v.handoff;
  if (!obj(handoff) || handoff.hypothesis_id !== v.hypothesis_id || handoff.intervention_id !== v.proposal.intervention_id || handoff.intervention_type !== v.proposal.intervention_type || handoff.human_reviewed_intervention !== false) return false;
  if (!["training", "non_training", "investigate"].includes(handoff.decision_type as string)) return false;
  if (!["awaiting_solution_validation", "permitted", "withheld", "not_applicable"].includes(handoff.training_design_gate as string)) return false;
  const training = v.proposal.intervention_type === "training" || v.proposal.intervention_type === "practice_simulation";
  if (handoff.decision_type !== (training ? "training" : v.proposal.intervention_type === "investigate_further" ? "investigate" : "non_training")) return false;
  if (v.solution_validation === null) {
    return v.status === "intervention_proposed" && handoff.solution_validation_id === null && handoff.solution_status === null &&
      handoff.training_design_gate === (training ? "awaiting_solution_validation" : "not_applicable");
  }
  if (!validation(v.solution_validation) || v.solution_validation.intervention_id !== v.proposal.intervention_id || v.solution_validation.hypothesis_id !== v.hypothesis_id) return false;
  if (v.status !== v.solution_validation.solution_status || handoff.solution_status !== v.status || handoff.solution_validation_id !== v.solution_validation.solution_validation_id) return false;
  return handoff.training_design_gate === (training ? v.status === "solution_validated" ? "permitted" : "withheld" : "not_applicable");
}

/** Plain-language gate description. The gate is a lifecycle projection, never an approval. */
export function gateText(gate: TrainingDesignGate, type: InterventionType, status?: InterventionRecord["status"]): string {
  const kind = type.replaceAll("_", " ");
  if (gate === "permitted") return `Training design may proceed on this ${kind} proposal. The solution review did not question it; a human has not approved it, and any design still needs independent alignment review.`;
  if (gate === "withheld") return `Training design is withheld. The solution review questioned this ${kind} proposal, so nothing is handed to the training generator.`;
  if (gate === "not_applicable" && status === "solution_questioned") return `This ${kind} proposal does not call for training, but the solution review questioned its fit. It is withheld from M5; a corrected proposal needs a new diagnosis review run.`;
  if (gate === "not_applicable") return `This ${kind} proposal does not call for training. Once aligned, it can be recorded as a non-training decision; no training outline, activities, practice, or rubric will be generated.`;
  return "Validate the solution before anything is handed downstream.";
}
