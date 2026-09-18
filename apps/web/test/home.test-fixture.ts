import type { DesignResult } from "../lib/designs";
import type { EvidenceValidation, RecordState, Signal } from "../lib/diagnostics";
import type { HomeSources, InsightSources, RuntimeMode } from "../lib/home/read-model";
import { designFixture } from "./design-workspace.test-fixture";

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
  intervention_provider: "controlled_fixture",
  solution_validator: "controlled_fixture",
  evaluation_count: 20,
  signal_count: 3,
};
export const realMode: RuntimeMode = {
  mode: "real_results_cx",
  diagnostic_provider: "unavailable",
  remote_diagnosis: "unavailable",
  design_provider: "unavailable",
  intervention_provider: "unavailable",
  solution_validator: "unavailable",
  evaluation_count: 20,
  signal_count: 3,
};

/**
 * A provider-backed AWS-5 package for the validated diagnosis `hyp_1`: the M5 fixture plus the
 * design basis, a scripted turn with facilitator cue, a knowledge check, and a missing detail.
 */
export function providerPackage(): DesignResult {
  const base = designFixture("training");
  const d = base.training_design!;
  const run = base.run_id;
  return {
    ...base,
    generation_mode: "provider",
    intervention: { ...base.intervention, intervention_id: "int_1", solution_validation_id: "sol_1" },
    training_design: {
      ...d,
      objectives: [{ ...d.objectives[0], standard: "both elements audible before the close" }],
      decision_checks: [{
        check_id: `${run}/C1`, objective_ids: [`${run}/O1`], situation: "The member asks what happens next.",
        question: "What should the representative do before closing?",
        options: [
          { option_id: `${run}/C1/A`, response: "State the next step and confirm understanding", feedback: "Correct: both elements close the gap.", correct: true },
          { option_id: `${run}/C1/B`, response: "Thank the member and close", feedback: "The next step is missing.", correct: false },
          { option_id: `${run}/C1/C`, response: "Transfer the call", feedback: "Not warranted.", correct: false },
          { option_id: `${run}/C1/D`, response: "Repeat the account number", feedback: "Does not address clarity.", correct: false },
        ],
      }],
      practice_scenarios: [{
        ...d.practice_scenarios[0],
        scenario_setup: "Facilitator plays the member with the request status visible.",
        escalation_expectation: null,
        beats: [
          { ...d.practice_scenarios[0].beats[0], expected_learner_behavior: "Name the specific next action.", facilitator_cue: "Listen for a confirming question.", behavior_ids: [`${run}/B1`] },
          { beat_id: `${run}/BEAT2`, trigger: "Learner names the action", likely_response: "When will that happen?", success_branch: "Agrees and thanks the learner", challenge_branch: "Asks again", expected_learner_behavior: "State timing as [PLACEHOLDER:M1].", facilitator_cue: "Watch for invented timing.", behavior_ids: [`${run}/B1`] },
        ],
      }],
      design_basis: {
        gap: { diagnosis_id: "hyp_1", signal_id: topSignal.signal_id, observed_behavior: "Missed clarity", cause_domain: "skill_gap", performance_dimension: "capability", human_revised: false },
        intervention: { run_id: run, decision_type: "training", intervention_type: "practice_simulation", intervention_id: "int_1", solution_validation_id: "sol_1", solution_alignment: "aligned", training_design_gate: "permitted", training_focus: "skill", validation_source: "aws4_solution_validator", summary: "Practice the resolution summary.", target_change: "State the next step and confirm member understanding before closing." },
        guidance_version: "resultscx-design-guidance/1",
        supplied_operational_context: [],
      },
      missing_operational_details: [{ detail_id: `${run}/M1`, placeholder: "[PLACEHOLDER:M1]", description: "Expected follow-up timing was not supplied.", needed_for: "Practice turn BEAT2" }],
      provider_metadata: { provider: "Amazon Bedrock", model: "global.anthropic.claude-sonnet-4-6" },
    },
  };
}

export function insight(overrides: Partial<InsightSources> = {}): InsightSources {
  return { signal: topSignal, record: awaiting, validation: null, intervention: null, design: null, ...overrides };
}

export function sources(overrides: Partial<HomeSources> = {}): HomeSources {
  return {
    mode: realMode,
    signals: [topSignal, secondSignal, cleanSignal],
    priority: insight(),
    ...overrides,
  };
}
