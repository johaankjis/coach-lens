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
export type RecordState = {
  provider_hypothesis: Hypothesis;
  status: "awaiting_review" | "approved" | "rejected" | "revised";
  human_revision: Diagnosis | null;
  revision_approved: boolean;
  events: ReviewEvent[];
};

export function validated(record: RecordState): boolean {
  return (
    record.status === "approved" ||
    (record.status === "revised" && record.revision_approved)
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

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/diagnostics${path}`, {
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
      detail = (await response.json()).detail ?? {};
    } catch {
      /* Proxy errors may not be JSON. */
    }
    const code =
      detail.code ??
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
      invalid_state_transition:
        "This review changed or can no longer accept that action. Refresh the diagnosis.",
      backend_unavailable:
        "The diagnostic service is unavailable. Check the local API and try again.",
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
  return response.json() as Promise<T>;
}

export const label = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
export const shortId = (value: string) =>
  value.length > 18 ? `${value.slice(0, 11)}…${value.slice(-5)}` : value;
