export type EvidenceReference = {
  item_id: string;
  evaluation_id: string | null;
};
export type Signal = {
  signal_id: string;
  domain: string;
  criterion: string;
  evaluated_results: number;
  evaluated_evaluations: number;
  total_evaluations: number;
  pass_count: number;
  fail_count: number;
  fail_rate: string;
  feedback_count: number;
  affected_evaluation_ids: string[];
};
export type EvidenceItem = {
  item_id: string;
  evaluation_id: string;
  domain: string;
  criterion: string;
  passed: boolean;
  answer: string;
  max_score: string;
  attained_score: string;
  evaluator_feedback: string | null;
  source_lineage: {
    source_filename: string;
    source_sheet: string;
    excel_row: number;
  };
};
export type EvidenceBundle = { signal: Signal; items: EvidenceItem[] };
export type Diagnosis = {
  observed_behavioral_defect: string;
  cause_domain: string;
  performance_dimension: string;
  explanation: string;
  supporting_evidence: EvidenceReference[];
  conflicting_evidence: EvidenceReference[];
  missing_evidence: string[];
};
export type Hypothesis = Diagnosis & {
  hypothesis_id: string;
  signal_id: string;
  provider_reported_confidence: string;
  provider_metadata: { provider: string; model: string | null };
};
export type ReviewEvent = {
  action: "approve" | "reject" | "revise";
  reviewer_id: string;
  occurred_at: string;
  rationale: string | null;
};
export const RECORD_STATUSES = [
  "awaiting_review",
  "approved",
  "rejected",
  "revised",
] as const;
export type RecordStatus = (typeof RECORD_STATUSES)[number];
export type RecordState = {
  provider_hypothesis: Hypothesis;
  status: RecordStatus;
  human_revision: Diagnosis | null;
  revision_approved: boolean;
  events: ReviewEvent[];
};

export type EvidenceValidation = {
  validation_id: string;
  hypothesis_id: string;
  signal_id: string;
  validation_outcome: "supported" | "partially_supported" | "unsupported" | "insufficient_evidence";
  semantic_status: "evidence_validated" | "evidence_questioned";
  support_assessment: string;
  supported_reference_ids: string[];
  contradicting_reference_ids: string[];
  unsupported_claims: string[];
  missing_evidence: string[];
  provider_reported_confidence: number;
};

/** Validated only when the M3 backend recorded an approval; frontend state never sets this. */
export function validated(record: RecordState): boolean {
  return (
    record.status === "approved" ||
    (record.status === "revised" && record.revision_approved === true)
  );
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

const MALFORMED = () =>
  new ApiError(
    0,
    "malformed_response",
    "The diagnostic service returned an unexpected response. Refresh and try again.",
  );

// Runtime shape checks for high-consequence fields. TypeScript types do not validate
// network responses, and a malformed record must never render as validated or crash the
// workspace. Only the fields the UI relies on to show status, cause, and citations are checked.
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(isString);
const isReference = (value: unknown): value is EvidenceReference =>
  isRecord(value) &&
  isString(value.item_id) &&
  (value.evaluation_id === null || isString(value.evaluation_id));
const isReferenceArray = (value: unknown): value is EvidenceReference[] =>
  Array.isArray(value) && value.every(isReference);

function isDiagnosis(value: unknown): value is Diagnosis {
  return (
    isRecord(value) &&
    isString(value.observed_behavioral_defect) &&
    isString(value.cause_domain) &&
    isString(value.performance_dimension) &&
    isString(value.explanation) &&
    isReferenceArray(value.supporting_evidence) &&
    isReferenceArray(value.conflicting_evidence) &&
    isStringArray(value.missing_evidence)
  );
}
function isHypothesis(value: unknown): value is Hypothesis {
  return (
    isDiagnosis(value) &&
    isString((value as Record<string, unknown>).hypothesis_id) &&
    isString((value as Record<string, unknown>).signal_id) &&
    isString((value as Record<string, unknown>).provider_reported_confidence) &&
    isRecord((value as Record<string, unknown>).provider_metadata) &&
    isString(
      (
        (value as Record<string, unknown>).provider_metadata as Record<
          string,
          unknown
        >
      ).provider,
    )
  );
}
function isEvent(value: unknown): value is ReviewEvent {
  return (
    isRecord(value) &&
    (value.action === "approve" ||
      value.action === "reject" ||
      value.action === "revise") &&
    isString(value.reviewer_id) &&
    isString(value.occurred_at) &&
    (value.rationale === null ||
      value.rationale === undefined ||
      isString(value.rationale))
  );
}
export function isRecordState(value: unknown): value is RecordState {
  return (
    isRecord(value) &&
    isHypothesis(value.provider_hypothesis) &&
    RECORD_STATUSES.includes(value.status as RecordStatus) &&
    (value.human_revision === null || isDiagnosis(value.human_revision)) &&
    typeof value.revision_approved === "boolean" &&
    Array.isArray(value.events) &&
    value.events.every(isEvent)
  );
}
export function isEvidenceValidation(value: unknown): value is EvidenceValidation {
  return isRecord(value) && isString(value.validation_id) &&
    isString(value.hypothesis_id) && isString(value.signal_id) &&
    ["supported", "partially_supported", "unsupported", "insufficient_evidence"].includes(value.validation_outcome as string) &&
    ["evidence_validated", "evidence_questioned"].includes(value.semantic_status as string) &&
    isString(value.support_assessment) && isStringArray(value.supported_reference_ids) &&
    isStringArray(value.contradicting_reference_ids) &&
    isStringArray(value.unsupported_claims) && isStringArray(value.missing_evidence) &&
    typeof value.provider_reported_confidence === "number";
}
export function isSignal(value: unknown): value is Signal {
  return (
    isRecord(value) &&
    isString(value.signal_id) &&
    isString(value.domain) &&
    isString(value.criterion) &&
    typeof value.evaluated_results === "number" &&
    typeof value.evaluated_evaluations === "number" &&
    typeof value.total_evaluations === "number" &&
    typeof value.pass_count === "number" &&
    typeof value.fail_count === "number" &&
    isString(value.fail_rate) &&
    typeof value.feedback_count === "number"
  );
}
function isEvidenceItem(value: unknown): value is EvidenceItem {
  return (
    isRecord(value) &&
    isString(value.item_id) &&
    isString(value.evaluation_id) &&
    isString(value.criterion) &&
    typeof value.passed === "boolean" &&
    isString(value.answer) &&
    isString(value.max_score) &&
    isString(value.attained_score) &&
    (value.evaluator_feedback === null || isString(value.evaluator_feedback)) &&
    isRecord(value.source_lineage) &&
    isString(value.source_lineage.source_filename) &&
    isString(value.source_lineage.source_sheet) &&
    typeof value.source_lineage.excel_row === "number"
  );
}
export function isEvidenceBundle(value: unknown): value is EvidenceBundle {
  return (
    isRecord(value) &&
    isSignal(value.signal) &&
    Array.isArray(value.items) &&
    value.items.every(isEvidenceItem)
  );
}
const everyItem =
  <T>(guard: (value: unknown) => value is T) =>
  (value: unknown): value is T[] =>
    Array.isArray(value) && value.every(guard);
export const isSignalList = everyItem(isSignal);
export const isRecordList = everyItem(isRecordState);

export async function api<T>(
  path: string,
  guard: (value: unknown) => value is T,
  options?: RequestInit,
  base: "diagnostics" | "designs" = "diagnostics",
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/${base}${path}`, {
      ...options,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
  } catch {
    throw new ApiError(
      0,
      "backend_unavailable",
      "The diagnostic service is unavailable. Check the local API and try again.",
    );
  }
  if (!response.ok) {
    let detail: { code?: string; message?: string } = {};
    try {
      const body: unknown = await response.json();
      if (isRecord(body) && isRecord(body.detail)) detail = body.detail;
    } catch {
      /* Proxy errors may not be JSON. */
    }
    const code =
      (isString(detail.code) ? detail.code : undefined) ??
      (response.status === 502 ? "backend_unavailable" : "request_failed");
    const message: Record<string, string> = {
      reasoner_unavailable:
        "No reasoning provider is configured. Review the observed evidence or use the local demo setup.",
      invalid_provider_output:
        "The diagnostic provider returned an invalid hypothesis. No diagnosis was saved.",
      invalid_evidence_reference:
        "The provider cited evidence outside this signal. No diagnosis was saved.",
      evidence_mismatch:
        "The diagnostic evidence did not match this signal. No diagnosis was saved.",
      reasoner_failure:
        "The diagnostic provider failed. No diagnosis was saved.",
      validator_unavailable: "No semantic evidence validator is configured.",
      validator_failure: "The evidence validator failed. No validation was saved.",
      invalid_validator_output: "The evidence validator returned invalid output. No validation was saved.",
      invalid_state_transition:
        "This review changed or can no longer accept that action. Refresh the diagnosis.",
      backend_unavailable:
        "The diagnostic service is unavailable. Check the local API and try again.",
      design_provider_unavailable:
        "No design provider is configured. Use the controlled synthetic demo or configure a provider.",
      invalid_design_output:
        "The design provider returned invalid output. No design was saved.",
      design_provider_failure:
        "The design provider failed. No design was saved.",
      diagnosis_not_approved:
        "A human-approved diagnosis is required before design can start.",
    };
    throw new ApiError(
      response.status,
      code,
      message[code] ??
        (response.status === 422
          ? "The review was rejected. Check the required fields and evidence references."
          : "The request could not be completed. Try again."),
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw MALFORMED();
  }
  if (!guard(payload)) throw MALFORMED();
  return payload;
}

export const label = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
export const shortId = (value: string) =>
  value.length > 18 ? `${value.slice(0, 11)}…${value.slice(-5)}` : value;
