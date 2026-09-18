import type { EvidenceValidation, RecordState, Signal } from "../lib/diagnostics";
import type { HomeSources, RuntimeMode } from "../lib/home/read-model";

export const topSignal: Signal = {
  signal_id: "sig_top",
  domain: "member_experience",
  criterion: "Resolution clarity",
  evaluated_results: 12,
  evaluated_evaluations: 12,
  total_evaluations: 20,
  pass_count: 5,
  fail_count: 7,
  fail_rate: "0.5833",
  feedback_count: 9,
  affected_evaluation_ids: ["eval_1", "eval_2", "eval_3"],
};
export const secondSignal: Signal = {
  ...topSignal,
  signal_id: "sig_second",
  domain: "compliance",
  criterion: "HIPAA verification",
  fail_count: 3,
  pass_count: 9,
  fail_rate: "0.25",
  affected_evaluation_ids: ["eval_4"],
};
export const cleanSignal: Signal = {
  ...topSignal,
  signal_id: "sig_clean",
  domain: "call_flow",
  criterion: "Greeting",
  fail_count: 0,
  pass_count: 12,
  fail_rate: "0",
  affected_evaluation_ids: [],
};

export const awaiting: RecordState = {
  provider_hypothesis: {
    hypothesis_id: "hyp_1",
    signal_id: topSignal.signal_id,
    observed_behavioral_defect: "Agents close calls without confirming the next step.",
    cause_domain: "skill_gap",
    performance_dimension: "capability",
    explanation: "Failed rows show summaries that omit the follow-up action.",
    supporting_evidence: [
      { item_id: "ev_1", evaluation_id: "eval_1" },
      { item_id: "signal", evaluation_id: null },
    ],
    conflicting_evidence: [{ item_id: "ev_2", evaluation_id: "eval_2" }],
    missing_evidence: ["Observe a live call"],
    provider_reported_confidence: "0.78",
    provider_metadata: { provider: "test-provider", model: "test-model" },
  },
  status: "awaiting_review",
  human_revision: null,
  revision_approved: false,
  events: [],
};
export const fixtureRecord: RecordState = {
  ...awaiting,
  provider_hypothesis: {
    ...awaiting.provider_hypothesis,
    provider_metadata: { provider: "m4-demo-fixture", model: null },
  },
};
export const approved: RecordState = {
  ...awaiting,
  status: "approved",
  events: [{ action: "approve", reviewer_id: "qa-lead", occurred_at: "2026-09-17T12:00:00Z", rationale: null }],
};
export const revisedPending: RecordState = {
  ...awaiting,
  status: "revised",
  human_revision: {
    ...awaiting.provider_hypothesis,
    cause_domain: "process_gap",
    performance_dimension: "undetermined",
    explanation: "Reviewer found a process issue.",
  },
  events: [{ action: "revise", reviewer_id: "qa-2", occurred_at: "2026-09-17T12:00:00Z", rationale: "Process evidence" }],
};
export const revisedApproved: RecordState = {
  ...revisedPending,
  revision_approved: true,
  events: [
    ...revisedPending.events,
    { action: "approve", reviewer_id: "qa-lead", occurred_at: "2026-09-17T13:00:00Z", rationale: null },
  ],
};
export const rejected: RecordState = {
  ...awaiting,
  status: "rejected",
  events: [{ action: "reject", reviewer_id: "qa-3", occurred_at: "2026-09-17T12:00:00Z", rationale: "Evidence too thin" }],
};

export const validatedReview: EvidenceValidation = {
  validation_id: "val_1",
  hypothesis_id: "hyp_1",
  signal_id: topSignal.signal_id,
  assessed_proposal: "provider_hypothesis",
  validation_outcome: "supported",
  semantic_status: "evidence_validated",
  support_assessment: "The cited rows show the missing next-step summary.",
  supported_reference_ids: ["EVID-001"],
  contradicting_reference_ids: [],
  supported_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }],
  contradicting_evidence: [],
  unsupported_claims: [],
  missing_evidence: [],
  provider_reported_confidence: 0.8,
};
export const questionedReview: EvidenceValidation = {
  ...validatedReview,
  validation_id: "val_2",
  validation_outcome: "unsupported",
  semantic_status: "evidence_questioned",
  support_assessment: "The cited failures do not establish a skill gap.",
  unsupported_claims: ["Skill gap is unproven"],
  missing_evidence: ["Direct observation"],
  provider_reported_confidence: 0.2,
};

export const demoMode: RuntimeMode = {
  mode: "synthetic_demo",
  diagnostic_provider: "controlled_fixture",
  remote_diagnosis: "local_fixture",
  design_provider: "controlled_fixture",
  evaluation_count: 20,
  signal_count: 3,
};
export const realMode: RuntimeMode = {
  mode: "real_results_cx",
  diagnostic_provider: "unavailable",
  remote_diagnosis: "unavailable",
  design_provider: "unavailable",
  evaluation_count: 20,
  signal_count: 3,
};

export function sources(overrides: Partial<HomeSources> = {}): HomeSources {
  return {
    mode: realMode,
    signals: [topSignal, secondSignal, cleanSignal],
    priority: { signal: topSignal, record: awaiting, validation: null, design: null },
    ...overrides,
  };
}
