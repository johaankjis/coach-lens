import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DesignWorkspace from "../app/design-workspace";
import ReviewWorkspace from "../app/review-workspace";
import { ALIGNMENT_DIMENSIONS, isAlignmentReview, type AlignmentReview } from "../lib/designs";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";
import type { EvidenceBundle, RecordState, Signal } from "../lib/diagnostics";

const run = "design_1";

function alignmentReview(overrides: Partial<AlignmentReview> = {}): AlignmentReview {
  const dimensions = Object.fromEntries(ALIGNMENT_DIMENSIONS.map((name) => [name, { outcome: "aligned", assessment: `${name} holds.`, misaligned_element_ids: [] }])) as unknown as AlignmentReview["dimensions"];
  return {
    alignment_review_id: "alr_1", run_id: run, diagnosis_id: "hyp_1", intervention_id: "int_abc", solution_validation_id: "sol_def",
    design_digest: "digest", assessed: "training_design_package", structural_trace: "structural_references_only",
    overall_outcome: "aligned", design_status: "design_aligned",
    overall_assessment: "The package trains the confirmed closing behavior.", dimensions,
    misaligned_element_ids: [], unsupported_assumptions: [], missing_information: [],
    provider_reported_confidence: 0.8, provider_metadata: { provider: "Amazon Bedrock", model: "global.anthropic.claude-sonnet-4-6", generation_mode: "provider" },
    created_at: "2026-09-18T00:00:00Z", ...overrides,
  };
}

function questionedReview(): AlignmentReview {
  const review = alignmentReview({ overall_outcome: "misaligned", design_status: "design_questioned",
    overall_assessment: "The activity trains documentation, not the resolution explanation.",
    misaligned_element_ids: [`${run}/A1`], unsupported_assumptions: ["Assumes a follow-up message is sent automatically."],
    missing_information: ["Which resolution options agents may offer."] });
  review.dimensions.objective_to_activity = { outcome: "misaligned", assessment: "The worksheet does not practice the objective.", misaligned_element_ids: [`${run}/A1`] };
  return review;
}

describe("AWS-6 alignment review guard", () => {
  it("accepts coherent reviews and refuses malformed or incoherent ones", () => {
    expect(isAlignmentReview(alignmentReview())).toBe(true);
    expect(isAlignmentReview(questionedReview())).toBe(true);
    const base = alignmentReview();
    expect(isAlignmentReview({ ...base, design_status: "design_questioned" })).toBe(false); // aligned must be design_aligned
    expect(isAlignmentReview({ ...base, overall_outcome: "misaligned" })).toBe(false); // and misaligned may not be design_aligned
    expect(isAlignmentReview({ ...base, overall_outcome: "supported" })).toBe(false);
    expect(isAlignmentReview({ ...base, structural_trace: "semantically_aligned" })).toBe(false);
    expect(isAlignmentReview({ ...base, assessed: "diagnosis" })).toBe(false);
    expect(isAlignmentReview({ ...base, misaligned_element_ids: [`${run}/A1`] })).toBe(false); // aligned names nothing
    expect(isAlignmentReview({ ...base, unsupported_assumptions: ["x"] })).toBe(false);
    expect(isAlignmentReview({ ...base, dimensions: { ...base.dimensions, practice_to_rubric: { outcome: "misaligned", assessment: "x", misaligned_element_ids: [] } } })).toBe(false);
    expect(isAlignmentReview({ ...base, dimensions: { ...base.dimensions, practice_to_rubric: undefined } })).toBe(false);
    expect(isAlignmentReview({ ...base, dimensions: { ...base.dimensions, gap_to_target_behavior: { outcome: "aligned", assessment: "x", misaligned_element_ids: [`${run}/B1`] } } })).toBe(false);
    expect(isAlignmentReview({ ...base, provider_reported_confidence: "0.8" })).toBe(false);
    expect(isAlignmentReview({ ...base, provider_reported_confidence: 1.5 })).toBe(false);
    expect(isAlignmentReview({ ...base, provider_metadata: undefined })).toBe(false);
    expect(isAlignmentReview({ ...base, overall_assessment: "" })).toBe(false);
    expect(isAlignmentReview(null)).toBe(false);
    expect(isAlignmentReview("truncated")).toBe(false);
  });
});

describe("AWS-6 alignment check in the design workspace", () => {
  it("offers the check and keeps the AWS-5 status until a review exists", () => {
    const onCheckAlignment = vi.fn();
    render(<DesignWorkspace result={designFixture()} onCheckAlignment={onCheckAlignment} />);
    expect(screen.getByRole("status")).toHaveTextContent("READY FOR ALIGNMENT REVIEW");
    expect(screen.getByRole("heading", { name: "AI semantic design review" })).toBeInTheDocument();
    expect(screen.getByText(/structural trace only proves the references/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CHECK ALIGNMENT" }));
    expect(onCheckAlignment).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("DESIGN ALIGNED")).not.toBeInTheDocument();
    expect(screen.queryByText("DESIGN QUESTIONED")).not.toBeInTheDocument();
  });

  it("shows a truthful pending state and no button for non-training results", () => {
    const { unmount } = render(<DesignWorkspace result={designFixture()} onCheckAlignment={() => undefined} checkingAlignment />);
    expect(screen.getByText("Reviewing design alignment…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "CHECK ALIGNMENT" })).toBeDisabled();
    unmount();
    const disabled = render(<DesignWorkspace result={designFixture()} onCheckAlignment={() => undefined} alignmentDisabled />);
    expect(screen.getByRole("button", { name: "CHECK ALIGNMENT" })).toBeDisabled();
    expect(screen.queryByText("Reviewing design alignment…")).not.toBeInTheDocument();
    disabled.unmount();
    for (const kind of ["non_training", "investigate"] as const) {
      const rendered = render(<DesignWorkspace result={designFixture(kind)} onCheckAlignment={() => undefined} />);
      expect(screen.queryByRole("button", { name: "CHECK ALIGNMENT" })).not.toBeInTheDocument();
      expect(screen.queryByText("Alignment Check")).not.toBeInTheDocument();
      rendered.unmount();
    }
  });

  it("renders an aligned review as design_aligned with explicitly non-calibrated confidence", () => {
    render(<DesignWorkspace result={designFixture()} alignmentReview={alignmentReview()} onCheckAlignment={() => undefined} />);
    const statuses = screen.getAllByRole("status");
    expect(statuses[0]).toHaveTextContent("DESIGN ALIGNED");
    expect(statuses[1]).toHaveTextContent("DESIGN ALIGNED · Aligned");
    expect(screen.queryByRole("button", { name: "CHECK ALIGNMENT" })).not.toBeInTheDocument();
    const section = screen.getByRole("region", { name: "Alignment check" });
    expect(within(section).getByText("Alignment Check")).toBeInTheDocument();
    expect(within(section).getByText("The package trains the confirmed closing behavior.")).toBeInTheDocument();
    expect(within(section).getByText("Validator-reported confidence")).toBeInTheDocument();
    expect(within(section).getByText("0.8")).toBeInTheDocument();
    expect(within(section).getByText(/not a statistically calibrated probability/)).toBeInTheDocument();
    expect(within(section).getByText("structural_references_only")).toBeInTheDocument();
    expect(within(section).getAllByText("None named.")).toHaveLength(3);
    expect(within(section).getByText(/Nothing has been deployed and no outcome has been measured/)).toBeInTheDocument();
    expect(within(section).getByText(/AI semantic review \(Amazon Bedrock/)).toBeInTheDocument();
    expect(screen.getByText(/found it addresses the confirmed gap\. Not deployed/)).toBeInTheDocument();
    for (const claim of [/validated training/i, /approved training/i, /deployed training/i, /improved/i])
      expect(screen.queryByText(claim)).not.toBeInTheDocument();
  });

  it("renders a questioned review with the problematic elements, assumptions, and missing information", () => {
    render(<DesignWorkspace result={designFixture()} alignmentReview={questionedReview()} />);
    expect(screen.getAllByRole("status")[0]).toHaveTextContent("DESIGN QUESTIONED");
    const section = screen.getByRole("region", { name: "Alignment check" });
    expect(section).toHaveClass("questioned");
    expect(within(section).getByText("DESIGN QUESTIONED · Misaligned")).toBeInTheDocument();
    expect(within(section).getByText("Objective → activity").closest("li")).toHaveClass("flagged");
    expect(within(section).getByText("Confirmed gap → target behavior").closest("li")).not.toHaveClass("flagged");
    expect(within(section).getByText("The worksheet does not practice the objective.")).toBeInTheDocument();
    expect(within(section).getByText("Elements: A1")).toBeInTheDocument();
    expect(within(section).getByText("A1", { selector: "dd" })).toBeInTheDocument();
    expect(within(section).getByText("Assumes a follow-up message is sent automatically.")).toBeInTheDocument();
    expect(within(section).getByText("Which resolution options agents may offer.")).toBeInTheDocument();
    expect(screen.getByText(/alignment review questioned it/)).toBeInTheDocument();
    // The AWS-5 package itself is rendered unchanged beside the verdict.
    expect(screen.getByText("State next step and check understanding")).toHaveClass("target-statement");
    expect(screen.getByRole("heading", { name: "Practice closure" })).toBeInTheDocument();
  });

  it("ignores a review that belongs to another design run", () => {
    render(<DesignWorkspace result={designFixture()} alignmentReview={alignmentReview({ run_id: "design_other" })} onCheckAlignment={() => undefined} />);
    expect(screen.getByRole("status")).toHaveTextContent("READY FOR ALIGNMENT REVIEW");
    expect(screen.getByRole("button", { name: "CHECK ALIGNMENT" })).toBeInTheDocument();
  });
});

// --- Review workspace integration -------------------------------------------------------------

const signal: Signal = {
  signal_id: "sig_1", domain: "member_experience", criterion: "Resolution summary clarity",
  evaluated_results: 3, evaluated_evaluations: 3, total_evaluations: 3, pass_count: 1, fail_count: 2,
  fail_rate: "0.6667", feedback_count: 2, affected_evaluation_ids: ["eval_1", "eval_2"],
};
const evidence: EvidenceBundle = {
  signal,
  items: [{ item_id: "ev_1", evaluation_id: "eval_1", domain: "member_experience", criterion: "Resolution summary clarity", passed: false, answer: "No", max_score: "10", attained_score: "0", evaluator_feedback: "Missed next step", source_lineage: { source_filename: "synthetic.xlsx", source_sheet: "QA", excel_row: 2 } }],
};
const approved: RecordState = {
  provider_hypothesis: { hypothesis_id: "hyp_1", signal_id: "sig_1", observed_behavioral_defect: "Missed clarity", cause_domain: "skill_gap", performance_dimension: "capability", explanation: "Provider proposed a skill gap.", supporting_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }], conflicting_evidence: [], missing_evidence: [], provider_reported_confidence: "0.78", provider_metadata: { provider: "test-provider", model: null } },
  status: "approved", human_revision: null, revision_approved: false, events: [],
};
const reply = (value: unknown, status = 200): Response => ({ ok: status < 400, status, json: async () => value }) as Response;

function route(stored: AlignmentReview | null, onCheck: () => Response | Promise<Response>) {
  const mock = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/signals")) return reply([signal]);
    if (path.endsWith("/review-evidence")) return reply(evidence);
    if (path.endsWith("/hypotheses")) return reply([approved]);
    if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
    if (path.endsWith("/alignment-review") && init?.method === "POST") return onCheck();
    if (path.endsWith("/alignment-review")) return stored ? reply(stored) : reply({ detail: { code: "alignment_review_not_found" } }, 404);
    if (path.includes("/api/designs/")) return reply(designFixture());
    if (path.includes("/api/interventions/")) return reply(interventionFixture());
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

describe("AWS-6 alignment check in the review workspace", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("loads a stored review with the design and renders it without a button", async () => {
    route(questionedReview(), () => { throw new Error("must not post"); });
    render(<ReviewWorkspace />);
    expect(await screen.findByText("DESIGN QUESTIONED · Misaligned")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "CHECK ALIGNMENT" })).not.toBeInTheDocument();
    expect(screen.queryByText("READY FOR ALIGNMENT REVIEW")).not.toBeInTheDocument();
  });

  it("requests one review despite repeated clicks and shows the stored verdict", async () => {
    let complete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { complete = resolve; });
    const mock = route(null, () => pending);
    render(<ReviewWorkspace />);
    const button = await screen.findByRole("button", { name: "CHECK ALIGNMENT" });
    expect(screen.getByText("READY FOR ALIGNMENT REVIEW")).toBeInTheDocument();
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.getByText("Reviewing design alignment…")).toBeInTheDocument();
    complete(reply(alignmentReview()));
    expect(await screen.findByText("DESIGN ALIGNED · Aligned")).toBeInTheDocument();
    expect(mock.mock.calls.filter(([path, init]) => String(path).endsWith("/alignment-review") && init?.method === "POST")).toHaveLength(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not manufacture a review on failed or malformed API output", async () => {
    let response: Response = reply({ detail: { code: "invalid_alignment_output", message: "private" } }, 502);
    route(null, () => response);
    render(<ReviewWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: "CHECK ALIGNMENT" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("returned invalid output. No alignment review was saved.");
    expect(screen.queryByText(/DESIGN ALIGNED/)).not.toBeInTheDocument();
    expect(screen.getByText("READY FOR ALIGNMENT REVIEW")).toBeInTheDocument();
    response = reply({ ...alignmentReview(), design_status: "design_questioned" });
    fireEvent.click(screen.getByRole("button", { name: "CHECK ALIGNMENT" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected response");
    expect(screen.queryByText(/DESIGN ALIGNED/)).not.toBeInTheDocument();
    response = reply({ detail: { code: "alignment_validator_unavailable" } }, 503);
    fireEvent.click(screen.getByRole("button", { name: "CHECK ALIGNMENT" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No alignment validator is configured.");
  });
});
