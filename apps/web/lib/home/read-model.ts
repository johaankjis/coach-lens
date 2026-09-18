/**
 * Home / Command Center read-model.
 *
 * The Home page never computes QA statistics. Every number it shows is a value the backend
 * already returned (M2 counts through the M3 signal list, M3 review records, the AWS-3 semantic
 * review, the AWS-4 intervention record, and the AWS-5 design result). This module only maps
 * those payloads into display-ready, explicitly typed states, so the page can be rendered and
 * tested from a plain object.
 *
 * Stages the backend does not expose yet (AWS-6 alignment review, outcome measurement) have
 * typed slots here that render as pending. Nothing in this file invents a value for them.
 */
import type { DesignResult } from "../designs";
import {
  label,
  validated,
  type EvidenceReference,
  type EvidenceValidation,
  type RecordState,
  type Signal,
} from "../diagnostics";
import type { InterventionRecord, TrainingDesignGate } from "../interventions";

export const AGENT_INSIGHTS_PATH = "/agent-insights";
export const TRAINING_PATH = "/training";
export const ROLE_PLAY_PATH = "/role-play";
export const KPI_TRACKER_PATH = "/kpi-tracker";
export const DEMO_FIXTURE_PROVIDER = "m4-demo-fixture";

/** `GET /diagnostics/mode`: operator-visible provenance for the running backend process. */
export type RuntimeMode = {
  mode: string;
  diagnostic_provider: string;
  remote_diagnosis: string;
  design_provider: string;
  /** AWS-4 provider kinds; older API builds omit them. */
  intervention_provider?: string;
  solution_validator?: string;
  evaluation_count: number;
  signal_count: number;
};

export function isRuntimeMode(value: unknown): value is RuntimeMode {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const optionalString = (field: unknown) => field === undefined || typeof field === "string";
  return (
    typeof record.mode === "string" &&
    typeof record.diagnostic_provider === "string" &&
    typeof record.remote_diagnosis === "string" &&
    typeof record.design_provider === "string" &&
    optionalString(record.intervention_provider) &&
    optionalString(record.solution_validator) &&
    typeof record.evaluation_count === "number" &&
    typeof record.signal_count === "number"
  );
}

export type ProvenanceKind =
  | "synthetic_demo"
  | "real_results_cx"
  | "local_normalized"
  | "unconfigured"
  | "unknown";

export type Provenance = {
  kind: ProvenanceKind;
  /** Short badge text. */
  label: string;
  /** One sentence explaining what the badge means for the numbers on the page. */
  detail: string;
  diagnosticProvider: string;
  designProvider: string;
  interventionProvider: string;
  solutionValidator: string;
  evaluationCount: number | null;
  signalCount: number | null;
};

export type MetricReading =
  | { state: "available"; value: string; detail: string }
  | { state: "pending"; reason: string; note?: string }
  | { state: "unavailable"; reason: string };

export type SummaryMetricId = "agents" | "priority" | "qa" | "intervention";

export type SummaryMetric = {
  id: SummaryMetricId;
  label: string;
  /** Which milestone owns this number. Shown so a pending tile is never read as a bug. */
  source: string;
  reading: MetricReading;
};

export type PerformanceGap = {
  rank: number;
  signalId: string;
  domain: string;
  criterion: string;
  failCount: number;
  evaluatedResults: number;
  /** Backend-reported fail rate, formatted for display. */
  failRateLabel: string;
  /** Backend-reported fail rate parsed for bar width only; never recomputed. */
  failRateFraction: number;
  coverage: { evaluated: number; total: number };
  href: string;
};

export type DiagnosisOrigin = "ai" | "fixture";

export type WorkingDiagnosis =
  | { state: "not_requested" }
  | {
      state: "proposed";
      origin: DiagnosisOrigin;
      humanRevised: boolean;
      observedDefect: string;
      causeDomain: string;
      performanceDimension: string;
      explanation: string;
      confidence: { value: string; wording: string };
      provider: string;
    };

export type EvidenceReviewStatus =
  | { state: "not_applicable" }
  | { state: "not_run" }
  | {
      state: "evidence_validated" | "evidence_questioned";
      outcome: string;
      assessment: string;
      unsupportedClaims: number;
      missingEvidence: number;
    };

export type HumanValidationState =
  | "none"
  | "awaiting_review"
  | "approved"
  | "revised_pending"
  | "revised_approved"
  | "rejected";

export type HumanValidationStatus = {
  state: HumanValidationState;
  reviewer: string | null;
  rationale: string | null;
};

export type EvidencePreview = {
  supporting: EvidenceReference[];
  conflicting: EvidenceReference[];
  missing: string[];
};

export type NextStep = { label: string; detail: string; href: string };

/* ---------- AWS-4 intervention -------------------------------------------------------- */

export type SolutionReview = {
  /** Backend `solution_status`; never a human decision. */
  status: "solution_validated" | "solution_questioned";
  alignment: string;
  assessment: string;
  misalignedPoints: number;
  unsupportedAssumptions: number;
  missingInformation: number;
  origin: DiagnosisOrigin;
};

/**
 * The AWS-4 record for the validated diagnosis. `blocked` means no human-validated diagnosis
 * exists; `not_started` means nothing has been proposed for it yet. The other states carry the
 * backend's own status and gate. None of them is a human approval of the intervention.
 */
export type InterventionStage =
  | { state: "blocked" }
  | { state: "not_started" }
  | {
      state: "proposed" | "solution_validated" | "solution_questioned";
      interventionType: string;
      typeLabel: string;
      decisionType: "training" | "non_training" | "investigate";
      recommendation: string;
      targetChange: string;
      origin: DiagnosisOrigin;
      solution: SolutionReview | null;
      trainingDesignGate: TrainingDesignGate;
    };

/* ---------- AWS-5 training package ----------------------------------------------------- */

export type TrainingPackageSummary = {
  designStatus: DesignResult["status"];
  readyForAlignmentReview: boolean;
  origin: DiagnosisOrigin;
  targetBehaviors: string[];
  objectiveCount: number;
  outlineSectionCount: number;
  activityCount: number;
  knowledgeCheckCount: number;
  practiceScenarioCount: number;
  missingOperationalDetailCount: number;
  /** Sum of backend `duration_minutes` over outline sections, for display only. */
  plannedMinutes: number;
  trainingHref: string;
  rolePlayHref: string;
};

/**
 * `blocked`: an upstream human or AWS-4 step has not happened. `awaiting_solution`: a training
 * or practice proposal exists but its solution review has not run. `withheld`: the solution
 * review questioned a training proposal, so nothing was handed to the designer. `not_applicable`:
 * the validated intervention is not training. `permitted`: the AWS-4 gate allows design and no
 * package exists yet. `generated`: an AWS-5 package exists. Generated is never deployed.
 */
export type TrainingStage =
  | { state: "blocked"; reason: string }
  | { state: "awaiting_solution"; reason: string }
  | { state: "withheld"; reason: string }
  | { state: "not_applicable"; reason: string }
  | { state: "permitted"; reason: string }
  | ({ state: "generated" } & TrainingPackageSummary);

/* ---------- AWS-6 alignment (future) and outcome --------------------------------------- */

/**
 * Narrow slot for the AWS-6 alignment review. No contract is integrated, so the only states are
 * "not yet reviewed" (a package exists), "not applicable" (no training), and "blocked" (no
 * package). The AWS-6 lane replaces this when its read route merges.
 */
export type AlignmentStage =
  | { state: "blocked"; reason: string }
  | { state: "not_applicable"; reason: string }
  | { state: "pending"; reason: string };

export type OutcomeStage = { state: "pending"; reason: string };

/* ---------- Pipeline and downstream display -------------------------------------------- */

export type StatusTone =
  | "neutral"
  | "validated"
  | "caution"
  | "rejected"
  | "proposed"
  | "pending"
  | "not_applicable";

export type PipelineStepId =
  | "observed"
  | "diagnosed"
  | "evidence_reviewed"
  | "human_validated"
  | "intervention_proposed"
  | "solution_validated"
  | "training_generated"
  | "alignment";

export type PipelineStep = { id: PipelineStepId; name: string; tone: StatusTone; text: string };

export type DownstreamStageId = "intervention" | "training" | "alignment" | "outcome";

export type DownstreamStatus =
  | "pending_backend"
  | "blocked"
  | "not_started"
  | "proposed"
  | "validated"
  | "questioned"
  | "withheld"
  | "generated"
  | "not_applicable"
  | "pending";

export type DownstreamStage = {
  id: DownstreamStageId;
  label: string;
  source: string;
  status: DownstreamStatus;
  detail: string;
  /** Present only when a real page exists for the stage's current state. */
  href?: string;
  hrefLabel?: string;
};

export type PriorityInsight = {
  signalId: string;
  domain: string;
  criterion: string;
  failure: {
    failCount: number;
    evaluatedResults: number;
    failRateLabel: string;
    coverage: { evaluated: number; total: number };
    feedbackCount: number;
  };
  diagnosis: WorkingDiagnosis;
  evidenceReview: EvidenceReviewStatus;
  humanValidation: HumanValidationStatus;
  intervention: InterventionStage;
  training: TrainingStage;
  alignment: AlignmentStage;
  outcome: OutcomeStage;
  pipeline: PipelineStep[];
  evidence: EvidencePreview | null;
  nextStep: NextStep;
  reviewHref: string;
};

export type HomeReadModel = {
  provenance: Provenance;
  summary: SummaryMetric[];
  observedSignalCount: number;
  gaps: PerformanceGap[];
  priority: PriorityInsight | null;
  downstream: DownstreamStage[];
  /** Set when a page asked for a specific signal; `found` is false when Home fell back. */
  requested: { signalId: string; found: boolean } | null;
};

/** Raw backend payloads the loader collects. The builder is pure so tests can drive it. */
export type InsightSources = {
  signal: Signal;
  record: RecordState | null;
  validation: EvidenceValidation | null;
  intervention: InterventionRecord | null;
  design: DesignResult | null;
};

export type HomeSources = {
  mode: RuntimeMode | null;
  signals: Signal[];
  priority: InsightSources | null;
  requested?: { signalId: string; found: boolean } | null;
};

export const TOP_GAP_COUNT = 5;

export const agentInsightsHref = (signalId: string) =>
  `${AGENT_INSIGHTS_PATH}?signal=${encodeURIComponent(signalId)}`;
export const trainingHref = (signalId: string) =>
  `${TRAINING_PATH}?signal=${encodeURIComponent(signalId)}`;
export const rolePlayHref = (signalId: string) =>
  `${ROLE_PLAY_PATH}?signal=${encodeURIComponent(signalId)}`;

export const percentLabel = (rate: string) => `${(Number(rate) * 100).toFixed(1)}%`;

const PROVENANCE: Record<ProvenanceKind, Pick<Provenance, "label" | "detail">> = {
  synthetic_demo: {
    label: "Synthetic demo",
    detail:
      "Controlled synthetic QA records with fixed non-AI fixtures. Nothing here is ResultsCX output.",
  },
  real_results_cx: {
    label: "Real ResultsCX · local",
    detail:
      "Normalized ResultsCX workbooks loaded locally. Counts are M2 calculations; nothing is fabricated.",
  },
  local_normalized: {
    label: "Local normalized data",
    detail: "Normalized QA evaluations loaded from the configured local JSONL file.",
  },
  unconfigured: {
    label: "No data loaded",
    detail: "The diagnostic service is running without QA evaluations.",
  },
  unknown: {
    label: "Provenance unknown",
    detail: "The runtime mode could not be read. Treat every number as unverified.",
  },
};

export function buildProvenance(mode: RuntimeMode | null): Provenance {
  const kind: ProvenanceKind =
    mode === null
      ? "unknown"
      : mode.mode === "synthetic_demo" ||
          mode.mode === "real_results_cx" ||
          mode.mode === "local_normalized" ||
          mode.mode === "unconfigured"
        ? mode.mode
        : "unknown";
  return {
    kind,
    ...PROVENANCE[kind],
    diagnosticProvider: mode?.diagnostic_provider ?? "unknown",
    designProvider: mode?.design_provider ?? "unknown",
    interventionProvider: mode?.intervention_provider ?? "unknown",
    solutionValidator: mode?.solution_validator ?? "unknown",
    evaluationCount: mode?.evaluation_count ?? null,
    signalCount: mode?.signal_count ?? null,
  };
}

function originOf(record: RecordState): DiagnosisOrigin {
  return record.provider_hypothesis.provider_metadata.provider === DEMO_FIXTURE_PROVIDER
    ? "fixture"
    : "ai";
}

const stageOrigin = (metadata: { generation_mode?: string | null }): DiagnosisOrigin =>
  metadata.generation_mode === "controlled_fixture" ? "fixture" : "ai";

function humanValidation(record: RecordState | null): HumanValidationStatus {
  if (!record) return { state: "none", reviewer: null, rationale: null };
  const last = (action: "approve" | "reject" | "revise") =>
    [...record.events].reverse().find((event) => event.action === action) ?? null;
  if (record.status === "rejected") {
    const event = last("reject");
    return { state: "rejected", reviewer: event?.reviewer_id ?? null, rationale: event?.rationale ?? null };
  }
  if (record.status === "revised") {
    const event = record.revision_approved ? last("approve") : last("revise");
    return {
      state: record.revision_approved ? "revised_approved" : "revised_pending",
      reviewer: event?.reviewer_id ?? null,
      rationale: event?.rationale ?? null,
    };
  }
  if (record.status === "approved") {
    const event = last("approve");
    return { state: "approved", reviewer: event?.reviewer_id ?? null, rationale: null };
  }
  return { state: "awaiting_review", reviewer: null, rationale: null };
}

function workingDiagnosis(record: RecordState | null): WorkingDiagnosis {
  if (!record) return { state: "not_requested" };
  const origin = originOf(record);
  const current = record.human_revision ?? record.provider_hypothesis;
  return {
    state: "proposed",
    origin,
    humanRevised: record.human_revision !== null,
    observedDefect: current.observed_behavioral_defect,
    causeDomain: label(current.cause_domain),
    performanceDimension: label(current.performance_dimension),
    explanation: current.explanation,
    confidence: {
      value: record.provider_hypothesis.provider_reported_confidence,
      wording:
        origin === "fixture"
          ? "Fixed synthetic fixture value. No model reported it, and it is not a calibrated probability."
          : "Provider self-report for the original proposal. It is not a statistically calibrated probability.",
    },
    provider: record.provider_hypothesis.provider_metadata.provider,
  };
}

function evidenceReview(
  record: RecordState | null,
  validation: EvidenceValidation | null,
): EvidenceReviewStatus {
  if (!record) return { state: "not_applicable" };
  if (!validation || validation.hypothesis_id !== record.provider_hypothesis.hypothesis_id)
    return { state: "not_run" };
  return {
    state: validation.semantic_status,
    outcome: label(validation.validation_outcome),
    assessment: validation.support_assessment,
    unsupportedClaims: validation.unsupported_claims.length,
    missingEvidence: validation.missing_evidence.length,
  };
}

/** The AWS-4 record only counts when it belongs to the validated record Home summarizes. */
function interventionFor(record: RecordState | null, intervention: InterventionRecord | null) {
  if (!record || !validated(record) || !intervention) return null;
  return intervention.hypothesis_id === record.provider_hypothesis.hypothesis_id ? intervention : null;
}

function designFor(record: RecordState | null, design: DesignResult | null) {
  if (!record || !validated(record) || !design) return null;
  return design.diagnosis_id === record.provider_hypothesis.hypothesis_id ? design : null;
}

function interventionStage(record: RecordState | null, intervention: InterventionRecord | null): InterventionStage {
  if (!record || !validated(record)) return { state: "blocked" };
  if (!intervention) return { state: "not_started" };
  const review = intervention.solution_validation;
  return {
    state: intervention.status === "intervention_proposed" ? "proposed" : intervention.status,
    interventionType: intervention.proposal.intervention_type,
    typeLabel: label(intervention.proposal.intervention_type),
    decisionType: intervention.handoff.decision_type,
    recommendation: intervention.proposal.recommendation,
    targetChange: intervention.proposal.target_change,
    origin: stageOrigin(intervention.proposal.provider_metadata),
    solution: review
      ? {
          status: review.solution_status,
          alignment: label(review.alignment_outcome),
          assessment: review.alignment_assessment,
          misalignedPoints: review.misaligned_points.length,
          unsupportedAssumptions: review.unsupported_assumptions.length,
          missingInformation: review.missing_information.length,
          origin: stageOrigin(review.provider_metadata),
        }
      : null,
    trainingDesignGate: intervention.handoff.training_design_gate,
  };
}

function packageSummary(signalId: string, design: DesignResult): TrainingPackageSummary {
  const d = design.training_design!;
  return {
    designStatus: design.status,
    readyForAlignmentReview: design.status === "ready_for_alignment_review",
    origin: design.generation_mode === "controlled_fixture" ? "fixture" : "ai",
    targetBehaviors: d.target_behaviors.map((behavior) => behavior.description),
    objectiveCount: d.objectives.length,
    outlineSectionCount: d.outline.length,
    activityCount: d.activities.length,
    knowledgeCheckCount: d.decision_checks.length,
    practiceScenarioCount: d.practice_scenarios.length,
    missingOperationalDetailCount: d.missing_operational_details?.length ?? 0,
    plannedMinutes: d.outline.reduce((sum, section) => sum + section.duration_minutes, 0),
    trainingHref: trainingHref(signalId),
    rolePlayHref: rolePlayHref(signalId),
  };
}

function trainingStage(
  signalId: string,
  intervention: InterventionStage,
  design: DesignResult | null,
): TrainingStage {
  if (design?.training_design) return { state: "generated", ...packageSummary(signalId, design) };
  if (intervention.state === "blocked")
    return { state: "blocked", reason: "Requires a human-validated diagnosis and a solution-validated intervention." };
  if (intervention.state === "not_started")
    return { state: "blocked", reason: "No intervention has been proposed for the validated diagnosis." };
  const kind = intervention.typeLabel;
  if (intervention.decisionType !== "training") {
    return {
      state: "not_applicable",
      reason:
        intervention.state === "solution_questioned"
          ? `${kind} does not call for training, and the solution review questioned it. Nothing was handed downstream.`
          : intervention.state === "solution_validated"
            ? `${kind} was solution validated. It does not call for training, so no package is generated.`
            : `${kind} does not call for training. Its solution review has not run.`,
    };
  }
  if (intervention.state === "proposed")
    return { state: "awaiting_solution", reason: `${kind} is proposed. Training design waits for the solution review.` };
  if (intervention.state === "solution_questioned" || intervention.trainingDesignGate === "withheld")
    return { state: "withheld", reason: `The solution review questioned the ${kind.toLowerCase()} proposal, so training design is withheld.` };
  return { state: "permitted", reason: `${kind} is solution validated. No training package has been generated yet.` };
}

function alignmentStage(training: TrainingStage): AlignmentStage {
  if (training.state === "generated")
    return { state: "pending", reason: "Not yet reviewed. Independent alignment review of the package against the validated diagnosis is not integrated." };
  if (training.state === "not_applicable")
    return { state: "not_applicable", reason: "No training package exists to align, so alignment review does not apply." };
  return { state: "blocked", reason: "Requires a generated training package." };
}

const OUTCOME: OutcomeStage = {
  state: "pending",
  reason: "Outcome measurement pending. No post-intervention QA has been loaded to compare with the observed baseline.",
};

function pipeline(
  diagnosis: WorkingDiagnosis,
  evidence: EvidenceReviewStatus,
  human: HumanValidationStatus,
  intervention: InterventionStage,
  training: TrainingStage,
  alignment: AlignmentStage,
): PipelineStep[] {
  const diagnosed: PipelineStep =
    diagnosis.state === "proposed"
      ? { id: "diagnosed", name: "Diagnosed", tone: "proposed", text: diagnosis.humanRevised ? "Human revised" : "Proposed" }
      : { id: "diagnosed", name: "Diagnosed", tone: "neutral", text: "Not requested" };
  const reviewed: PipelineStep =
    evidence.state === "evidence_validated"
      ? { id: "evidence_reviewed", name: "Evidence reviewed", tone: "validated", text: "Validated" }
      : evidence.state === "evidence_questioned"
        ? { id: "evidence_reviewed", name: "Evidence reviewed", tone: "caution", text: "Questioned" }
        : { id: "evidence_reviewed", name: "Evidence reviewed", tone: "neutral", text: evidence.state === "not_run" ? "Not run" : "No diagnosis" };
  const validatedStep: PipelineStep = {
    id: "human_validated",
    name: "Human validated",
    ...({
      none: { tone: "neutral", text: "No diagnosis" },
      awaiting_review: { tone: "pending", text: "Awaiting review" },
      approved: { tone: "validated", text: "Approved" },
      revised_pending: { tone: "caution", text: "Revision awaiting approval" },
      revised_approved: { tone: "validated", text: "Revision approved" },
      rejected: { tone: "rejected", text: "Rejected" },
    } satisfies Record<HumanValidationState, { tone: StatusTone; text: string }>)[human.state],
  };
  const proposed: PipelineStep =
    intervention.state === "blocked"
      ? { id: "intervention_proposed", name: "Intervention proposed", tone: "neutral", text: "Blocked" }
      : intervention.state === "not_started"
        ? { id: "intervention_proposed", name: "Intervention proposed", tone: "pending", text: "Not proposed" }
        : { id: "intervention_proposed", name: "Intervention proposed", tone: "proposed", text: intervention.typeLabel };
  const solution: PipelineStep =
    intervention.state === "solution_validated"
      ? { id: "solution_validated", name: "Solution validated", tone: "validated", text: "Validated" }
      : intervention.state === "solution_questioned"
        ? { id: "solution_validated", name: "Solution validated", tone: "caution", text: "Questioned" }
        : intervention.state === "proposed"
          ? { id: "solution_validated", name: "Solution validated", tone: "pending", text: "Awaiting validation" }
          : { id: "solution_validated", name: "Solution validated", tone: "neutral", text: "Blocked" };
  const generated: PipelineStep = {
    id: "training_generated",
    name: "Training generated",
    ...({
      blocked: { tone: "neutral", text: "Blocked" },
      awaiting_solution: { tone: "neutral", text: "Awaiting solution" },
      withheld: { tone: "caution", text: "Withheld" },
      not_applicable: { tone: "not_applicable", text: "Not applicable" },
      permitted: { tone: "pending", text: "Not generated" },
      generated: { tone: "validated", text: "Generated" },
    } satisfies Record<TrainingStage["state"], { tone: StatusTone; text: string }>)[training.state],
  };
  const aligned: PipelineStep = {
    id: "alignment",
    name: "Alignment",
    ...({
      blocked: { tone: "neutral", text: "Blocked" },
      not_applicable: { tone: "not_applicable", text: "Not applicable" },
      pending: { tone: "pending", text: "Pending" },
    } satisfies Record<AlignmentStage["state"], { tone: StatusTone; text: string }>)[alignment.state],
  };
  return [
    { id: "observed", name: "Observed", tone: "validated", text: "Deterministic" },
    diagnosed,
    reviewed,
    validatedStep,
    proposed,
    solution,
    generated,
    aligned,
  ];
}

/**
 * One context-sensitive action. Every href is a real page: Agent Insights owns diagnosis review,
 * intervention proposal, solution validation, and design; Training and Role-Play only display.
 */
function nextStep(
  signal: Signal,
  record: RecordState | null,
  validation: EvidenceValidation | null,
  intervention: InterventionStage,
  training: TrainingStage,
): NextStep {
  const href = agentInsightsHref(signal.signal_id);
  if (!record && signal.fail_count === 0)
    return {
      label: "Inspect observed criterion",
      detail: "No failed results were observed for this criterion. Inspect its QA evidence in Agent Insights.",
      href,
    };
  if (!record)
    return {
      label: "Review observed evidence and run diagnosis",
      detail: "Open the evidence for this signal and ask the M3 reasoning workflow for a hypothesis.",
      href,
    };
  if (record.status === "rejected")
    return {
      label: "Request another hypothesis",
      detail: "The reviewer rejected this diagnosis. It is not ready for intervention.",
      href,
    };
  if (record.status === "revised" && !record.revision_approved)
    return {
      label: "Approve human revision",
      detail: "A reviewer corrected the proposal. The revision still needs its own approval.",
      href,
    };
  if (!validated(record))
    return validation
      ? {
          label: "Review diagnosis",
          detail: "Semantic evidence review is recorded. A human reviewer still decides.",
          href,
        }
      : {
          label: "Review diagnosis",
          detail: "Validate the evidence, then approve, revise, or reject the working diagnosis.",
          href,
        };
  if (intervention.state === "blocked" || intervention.state === "not_started")
    return {
      label: "Generate intervention",
      detail: "The diagnosis is human validated. Ask the AWS-4 reasoner what to do about it; training is not assumed.",
      href,
    };
  if (intervention.state === "proposed")
    return {
      label: "Validate solution",
      detail: `${intervention.typeLabel} is proposed. Ask the solution validator whether it addresses the validated cause.`,
      href,
    };
  if (intervention.state === "solution_questioned")
    return {
      label: "Review solution concerns",
      detail: `The solution review questioned the ${intervention.typeLabel.toLowerCase()} proposal. Training is withheld until a corrected proposal is reviewed.`,
      href,
    };
  if (training.state === "generated")
    return {
      label: "Review training package",
      detail: "An AWS-5 package is generated, not deployed. Independent alignment check is pending.",
      href: training.trainingHref,
    };
  if (intervention.decisionType === "investigate")
    return {
      label: "Review investigation recommendation",
      detail: "The validated recommendation is to gather more evidence before selecting an intervention.",
      href,
    };
  if (intervention.decisionType === "non_training")
    return {
      label: "Review validated process intervention",
      detail: `${intervention.typeLabel} was solution validated. It does not call for training.`,
      href,
    };
  return {
    label: "Generate training",
    detail: `${intervention.typeLabel} is solution validated. Ask the AWS-5 designer for the package in Agent Insights.`,
    href,
  };
}

function evidencePreview(record: RecordState | null): EvidencePreview | null {
  if (!record) return null;
  const current = record.human_revision ?? record.provider_hypothesis;
  return {
    supporting: current.supporting_evidence,
    conflicting: current.conflicting_evidence,
    missing: current.missing_evidence,
  };
}

export function buildPriorityInsight(source: InsightSources): PriorityInsight {
  const { signal, record, validation } = source;
  const interventionRecord = interventionFor(record, source.intervention);
  const design = designFor(record, source.design);
  const diagnosis = workingDiagnosis(record);
  const evidence = evidenceReview(record, validation);
  const human = humanValidation(record);
  const intervention = interventionStage(record, interventionRecord);
  const training = trainingStage(signal.signal_id, intervention, design);
  const alignment = alignmentStage(training);
  return {
    signalId: signal.signal_id,
    domain: label(signal.domain),
    criterion: signal.criterion,
    failure: {
      failCount: signal.fail_count,
      evaluatedResults: signal.evaluated_results,
      failRateLabel: percentLabel(signal.fail_rate),
      coverage: { evaluated: signal.evaluated_evaluations, total: signal.total_evaluations },
      feedbackCount: signal.feedback_count,
    },
    diagnosis,
    evidenceReview: evidence,
    humanValidation: human,
    intervention,
    training,
    alignment,
    outcome: OUTCOME,
    pipeline: pipeline(diagnosis, evidence, human, intervention, training, alignment),
    evidence: evidencePreview(record),
    nextStep: nextStep(signal, record, validation, intervention, training),
    reviewHref: agentInsightsHref(signal.signal_id),
  };
}

export function buildDownstream(insight: PriorityInsight | null): DownstreamStage[] {
  const intervention: DownstreamStage = {
    id: "intervention",
    label: "Intervention",
    source: "AWS-4 intervention reasoner and solution validator",
    ...(!insight || insight.intervention.state === "blocked"
      ? { status: "blocked" as const, detail: "Requires a human-validated diagnosis." }
      : insight.intervention.state === "not_started"
        ? { status: "not_started" as const, detail: "Diagnosis is human validated. No intervention has been proposed." }
        : insight.intervention.state === "proposed"
          ? {
              status: "proposed" as const,
              detail: `${insight.intervention.typeLabel} proposed: ${insight.intervention.recommendation} Solution review has not run.`,
              href: insight.reviewHref,
              hrefLabel: "Validate solution",
            }
          : insight.intervention.state === "solution_validated"
            ? {
                status: "validated" as const,
                detail: `${insight.intervention.typeLabel} solution validated (${insight.intervention.solution?.alignment ?? "aligned"}). Not a human approval of the intervention.`,
                href: insight.reviewHref,
                hrefLabel: "Review intervention",
              }
            : {
                status: "questioned" as const,
                detail: `${insight.intervention.typeLabel} solution questioned (${insight.intervention.solution?.alignment ?? "not aligned"}). ${insight.intervention.solution?.assessment ?? ""}`.trim(),
                href: insight.reviewHref,
                hrefLabel: "Review solution concerns",
              }),
  };
  const training: DownstreamStage = {
    id: "training",
    label: "Training",
    source: "AWS-5 training designer",
    ...(!insight
      ? { status: "blocked" as const, detail: "Requires a validated intervention decision." }
      : insight.training.state === "generated"
        ? {
            status: "generated" as const,
            detail: `${label(insight.training.designStatus)}. ${insight.training.outlineSectionCount} outline section${insight.training.outlineSectionCount === 1 ? "" : "s"}, ${insight.training.activityCount} activit${insight.training.activityCount === 1 ? "y" : "ies"}, ${insight.training.practiceScenarioCount} practice scenario${insight.training.practiceScenarioCount === 1 ? "" : "s"}. Generated, not deployed.`,
            href: insight.training.trainingHref,
            hrefLabel: "Open training package",
          }
        : insight.training.state === "withheld"
          ? { status: "withheld" as const, detail: insight.training.reason }
          : insight.training.state === "not_applicable"
            ? { status: "not_applicable" as const, detail: insight.training.reason }
            : insight.training.state === "permitted"
              ? { status: "not_started" as const, detail: insight.training.reason, href: insight.reviewHref, hrefLabel: "Generate training" }
              : { status: "blocked" as const, detail: insight.training.reason }),
  };
  const alignment: DownstreamStage = {
    id: "alignment",
    label: "Alignment",
    source: "AWS-6 alignment review",
    ...(!insight || insight.alignment.state === "blocked"
      ? { status: "blocked" as const, detail: insight?.alignment.reason ?? "Requires a generated training package." }
      : insight.alignment.state === "not_applicable"
        ? { status: "not_applicable" as const, detail: insight.alignment.reason }
        : { status: "pending" as const, detail: insight.alignment.reason }),
  };
  return [
    intervention,
    training,
    alignment,
    {
      id: "outcome",
      label: "Outcome",
      source: "Outcome measurement",
      status: "pending_backend",
      detail: OUTCOME.reason,
      href: KPI_TRACKER_PATH,
      hrefLabel: "Open KPI Tracker",
    },
  ];
}

function interventionTileNote(insight: PriorityInsight | null): string | undefined {
  if (!insight) return undefined;
  const { intervention, training } = insight;
  if (training.state === "generated") return "Selected insight: training package generated, alignment pending";
  if (training.state === "withheld") return "Selected insight: solution questioned, training withheld";
  if (intervention.state === "solution_validated") return `Selected insight: ${intervention.typeLabel.toLowerCase()} solution validated`;
  if (intervention.state === "solution_questioned") return `Selected insight: ${intervention.typeLabel.toLowerCase()} solution questioned`;
  if (intervention.state === "proposed") return `Selected insight: ${intervention.typeLabel.toLowerCase()} proposed`;
  if (intervention.state === "not_started") return "Selected insight: no intervention proposed";
  return "Selected insight: awaiting human validation";
}

export function buildSummary(provenance: Provenance, insight: PriorityInsight | null): SummaryMetric[] {
  const loaded = provenance.evaluationCount;
  return [
    {
      id: "agents",
      label: "Agents monitored",
      source: "M2 agent roster",
      reading: {
        state: "pending",
        reason: "The M2 API does not expose an agent roster.",
        note:
          loaded === null
            ? undefined
            : `${loaded} QA evaluation${loaded === 1 ? "" : "s"} loaded`,
      },
    },
    {
      id: "priority",
      label: "Priority issues",
      source: "Priority policy pending",
      reading: {
        state: "pending",
        reason: "The backend has not classified or prioritized issues.",
        note:
          provenance.signalCount === null
            ? undefined
            : `${provenance.signalCount} observed criteria loaded`,
      },
    },
    {
      id: "qa",
      label: "Overall QA",
      source: "M2 aggregate scoring",
      reading: {
        state: "pending",
        reason: "The M2 API does not expose an overall QA score.",
        note:
          provenance.signalCount === null
            ? undefined
            : `${provenance.signalCount} criteria observed`,
      },
    },
    {
      id: "intervention",
      label: "Training / intervention",
      source: "AWS-4 / AWS-5",
      reading: {
        state: "pending",
        reason: "No team-wide intervention or training count is exposed by the backend.",
        note: interventionTileNote(insight),
      },
    },
  ];
}

export function buildHomeReadModel(sources: HomeSources): HomeReadModel {
  const provenance = buildProvenance(sources.mode);
  const priority = sources.priority ? buildPriorityInsight(sources.priority) : null;
  return {
    provenance,
    summary: buildSummary(provenance, priority),
    observedSignalCount: sources.signals.length,
    gaps: sources.signals.slice(0, TOP_GAP_COUNT).map((signal, index) => ({
      rank: index + 1,
      signalId: signal.signal_id,
      domain: label(signal.domain),
      criterion: signal.criterion,
      failCount: signal.fail_count,
      evaluatedResults: signal.evaluated_results,
      failRateLabel: percentLabel(signal.fail_rate),
      failRateFraction: Math.min(1, Math.max(0, Number(signal.fail_rate) || 0)),
      coverage: { evaluated: signal.evaluated_evaluations, total: signal.total_evaluations },
      href: agentInsightsHref(signal.signal_id),
    })),
    priority,
    downstream: buildDownstream(priority),
    requested: sources.requested ?? null,
  };
}
