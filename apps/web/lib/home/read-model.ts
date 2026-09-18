/**
 * Home / Command Center read-model.
 *
 * The Home page never computes QA statistics. Every number it shows is a value the backend
 * already returned (M2 counts through the M3 signal list, M3 review records, the AWS-3 semantic
 * review, and the M5 design result). This module only maps those payloads into display-ready,
 * explicitly typed states, so the page can be rendered and tested from a plain object.
 *
 * Future backend milestones (AWS-4 intervention validation, AWS-5 training status, AWS-6
 * alignment, outcome evaluation) have typed slots here that render as pending until their
 * contracts merge. Nothing in this file invents a value for them.
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

export const AGENT_INSIGHTS_PATH = "/agent-insights";
export const DEMO_FIXTURE_PROVIDER = "m4-demo-fixture";

/** `GET /diagnostics/mode`: operator-visible provenance for the running backend process. */
export type RuntimeMode = {
  mode: string;
  diagnostic_provider: string;
  remote_diagnosis: string;
  design_provider: string;
  evaluation_count: number;
  signal_count: number;
};

export function isRuntimeMode(value: unknown): value is RuntimeMode {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.mode === "string" &&
    typeof record.diagnostic_provider === "string" &&
    typeof record.remote_diagnosis === "string" &&
    typeof record.design_provider === "string" &&
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

export type DownstreamStageId = "intervention" | "training" | "alignment" | "outcome";

/**
 * Typed slot for stages the backend does not yet expose. `pending_backend` means the owning
 * milestone has not merged; `blocked` means an upstream human step has not happened; `proposed`
 * means an existing M5 proposal is recorded and still awaits its own validation.
 */
export type DownstreamStage = {
  id: DownstreamStageId;
  label: string;
  source: string;
  status: "pending_backend" | "blocked" | "not_started" | "proposed" | "not_applicable";
  detail: string;
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
};

/** Raw backend payloads the loader collects. The builder is pure so tests can drive it. */
export type HomeSources = {
  mode: RuntimeMode | null;
  signals: Signal[];
  priority: {
    signal: Signal;
    record: RecordState | null;
    validation: EvidenceValidation | null;
    design: DesignResult | null;
  } | null;
};

export const TOP_GAP_COUNT = 5;

export const agentInsightsHref = (signalId: string) =>
  `${AGENT_INSIGHTS_PATH}?signal=${encodeURIComponent(signalId)}`;

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
    evaluationCount: mode?.evaluation_count ?? null,
    signalCount: mode?.signal_count ?? null,
  };
}

function originOf(record: RecordState): DiagnosisOrigin {
  return record.provider_hypothesis.provider_metadata.provider === DEMO_FIXTURE_PROVIDER
    ? "fixture"
    : "ai";
}

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

function nextStep(
  signal: Signal,
  record: RecordState | null,
  validation: EvidenceValidation | null,
  design: DesignResult | null,
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
      label: "Request diagnostic hypothesis",
      detail: "Open the evidence for this signal and ask the M3 reasoning workflow for a hypothesis.",
      href,
    };
  if (record.status === "rejected")
    return {
      label: "Request another hypothesis",
      detail: "The reviewer rejected this diagnosis. It is not ready for design.",
      href,
    };
  if (validated(record))
    return design
      ? {
          label: "Review proposed intervention",
          detail: "An M5 proposal is recorded. Independent validation of it arrives with AWS-4.",
          href,
        }
      : {
          label: "Design intervention",
          detail: "The diagnosis is human validated. Ask CoachLens to propose the appropriate response.",
          href,
        };
  if (record.status === "revised")
    return {
      label: "Approve human revision",
      detail: "A reviewer corrected the proposal. The revision still needs its own approval.",
      href,
    };
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

export function buildPriorityInsight(
  source: NonNullable<HomeSources["priority"]>,
): PriorityInsight {
  const { signal, record, validation, design } = source;
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
    diagnosis: workingDiagnosis(record),
    evidenceReview: evidenceReview(record, validation),
    humanValidation: humanValidation(record),
    evidence: evidencePreview(record),
    nextStep: nextStep(signal, record, validation, design),
    reviewHref: agentInsightsHref(signal.signal_id),
  };
}

export function buildDownstream(
  source: HomeSources["priority"],
): DownstreamStage[] {
  const record = source?.record ?? null;
  const design = source?.design ?? null;
  const isValidated = record !== null && validated(record);
  const intervention: DownstreamStage = {
    id: "intervention",
    label: "Intervention",
    source: "AWS-4 intervention validator",
    ...(design
      ? {
          status: "proposed" as const,
          detail: `M5 proposed ${label(design.intervention.decision_type)} (${label(design.status)}). Validation of that proposal is pending AWS-4.`,
        }
      : isValidated
        ? { status: "not_started" as const, detail: "Diagnosis is human validated. No intervention has been requested." }
        : { status: "blocked" as const, detail: "Requires a human-validated diagnosis." }),
  };
  const training: DownstreamStage = {
    id: "training",
    label: "Training",
    source: "AWS-5 training designer",
    ...(design?.training_design
      ? {
          status: "proposed" as const,
          detail: "M5 training outline is recorded. Training status and delivery arrive with AWS-5.",
        }
      : design
        ? {
            status: "not_applicable" as const,
            detail: `M5 recommended ${label(design.intervention.decision_type)}, so no training outline exists.`,
          }
        : { status: "blocked" as const, detail: "Requires a validated intervention decision." }),
  };
  return [
    intervention,
    training,
    {
      id: "alignment",
      label: "Alignment",
      source: "AWS-6 alignment review",
      status: "pending_backend",
      detail: "Independent alignment review of training against the validated diagnosis is not implemented yet.",
    },
    {
      id: "outcome",
      label: "Outcome",
      source: "Outcome evaluation",
      status: "pending_backend",
      detail: "Later QA outcomes compared with the original evidence are not implemented yet.",
    },
  ];
}

export function buildSummary(
  provenance: Provenance,
  downstream: DownstreamStage[],
): SummaryMetric[] {
  const loaded = provenance.evaluationCount;
  const intervention = downstream.find((stage) => stage.id === "intervention");
  return [
    {
      id: "agents",
      label: "Agents monitored",
      source: "M2 agent roster",
      reading: {
        state: "pending",
        reason: "The M2 API does not expose an agent roster yet.",
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
        reason: "The M2 API does not expose an overall QA score yet.",
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
        reason: "Intervention validation and training status are not merged yet.",
        note: intervention ? `Selected insight: ${label(intervention.status)}` : undefined,
      },
    },
  ];
}

export function buildHomeReadModel(sources: HomeSources): HomeReadModel {
  const provenance = buildProvenance(sources.mode);
  const downstream = buildDownstream(sources.priority);
  return {
    provenance,
    summary: buildSummary(provenance, downstream),
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
    priority: sources.priority ? buildPriorityInsight(sources.priority) : null,
    downstream,
  };
}
