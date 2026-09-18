import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DesignWorkspace from "../app/design-workspace";
import ReviewWorkspace from "../app/review-workspace";
import type { EvidenceBundle, RecordState, Signal } from "../lib/diagnostics";
import { gateText, isInterventionRecord, type InterventionRecord } from "../lib/interventions";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";

const signal: Signal = {
  signal_id: "sig_1", domain: "member_experience", criterion: "Resolution clarity", evaluated_results: 2,
  evaluated_evaluations: 2, total_evaluations: 3, pass_count: 1, fail_count: 1, fail_rate: "0.5", feedback_count: 2,
  affected_evaluation_ids: ["eval_1"],
};
const evidence: EvidenceBundle = {
  signal,
  items: [
    { item_id: "ev_1", evaluation_id: "eval_1", domain: signal.domain, criterion: signal.criterion, passed: false, answer: "No",
      max_score: "10", attained_score: "2", evaluator_feedback: "Next step unclear",
      source_lineage: { source_filename: "synthetic.xlsx", source_sheet: "QA", excel_row: 2 } },
    { item_id: "ev_2", evaluation_id: "eval_2", domain: signal.domain, criterion: signal.criterion, passed: true, answer: "Yes",
      max_score: "10", attained_score: "10", evaluator_feedback: "Clear summary",
      source_lineage: { source_filename: "synthetic.xlsx", source_sheet: "QA", excel_row: 3 } },
  ],
};
const approved: RecordState = {
  provider_hypothesis: {
    hypothesis_id: "hyp_1", signal_id: "sig_1", observed_behavioral_defect: "One source QA result failed",
    cause_domain: "skill_gap", performance_dimension: "capability", explanation: "Provider proposed a skill gap.",
    supporting_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }], conflicting_evidence: [], missing_evidence: [],
    provider_reported_confidence: "0.78", provider_metadata: { provider: "test-provider", model: null },
  },
  status: "approved", human_revision: null, revision_approved: false,
  events: [{ action: "approve", reviewer_id: "supervisor-1", occurred_at: "2026-09-17T12:00:00Z", rationale: null }],
};

function reply(value: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => value } as Response;
}
let stored: InterventionRecord | null = null;
function route(mutation?: (path: string) => Promise<Response> | Response, records: RecordState[] = [approved]) {
  const mock = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST" && mutation) return mutation(path);
    if (path.endsWith("/signals")) return reply([signal]);
    if (path.endsWith("/review-evidence")) return reply(evidence);
    if (path.endsWith("/hypotheses")) return reply(records);
    if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
    if (path.includes("/api/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
    if (path.includes("/api/interventions/")) return stored ? reply(stored) : reply({ detail: { code: "intervention_not_found" } }, 404);
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
beforeEach(() => {
  vi.unstubAllGlobals();
  stored = null;
});
const loaded = () => screen.findByText("HUMAN VALIDATED");

describe("AWS-4 intervention and solution stages", () => {
  it("offers the intervention stage only after human validation and before any design action", async () => {
    route(undefined, [{ ...approved, status: "awaiting_review", events: [] }]);
    render(<ReviewWorkspace />);
    await screen.findByText("Provider proposed a skill gap.");
    expect(screen.queryByRole("button", { name: "Propose intervention" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
  });

  it("proposes an intervention and presents it as a non-human, non-training-by-default proposal", async () => {
    const mock = route((path) => {
      if (path.endsWith("/propose")) return reply(interventionFixture("practice_simulation", null));
      throw new Error(path);
    });
    render(<ReviewWorkspace />);
    await loaded();
    expect(screen.getByText("READY FOR INTERVENTION REVIEW")).toBeInTheDocument();
    expect(screen.getByText(/training has not yet been selected/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Propose intervention" }));
    const panel = await screen.findByRole("region", { name: "Proposed intervention" });
    expect(within(panel).getByText("Practice Simulation")).toBeInTheDocument();
    expect(within(panel).getByText("INTERVENTION PROPOSED · NOT HUMAN VALIDATED")).toBeInTheDocument();
    expect(within(panel).getByText("Rehearse the closing summary in short simulated calls.")).toBeInTheDocument();
    expect(within(panel).getByText("The validated skill gap is best closed by practice with feedback.")).toBeInTheDocument();
    expect(within(panel).getByText("State the next step and confirm member understanding before closing.")).toBeInTheDocument();
    expect(within(panel).getByText("Practice fits a capability skill gap; instruction alone would not.")).toBeInTheDocument();
    expect(within(panel).getByText("Only two evaluations were available.")).toBeInTheDocument();
    expect(within(panel).getByText("Direct observation of a live call")).toBeInTheDocument();
    expect(within(panel).getByText("0.6")).toBeInTheDocument();
    expect(within(panel).getByText(/not a statistically calibrated probability/)).toBeInTheDocument();
    expect(within(panel).getByText(/Supervisor supervisor-1 approved it with evidence review status: no semantic evidence review recorded/)).toBeInTheDocument();
    expect(within(panel).queryByText(/EVID-00/)).not.toBeInTheDocument();
    // The solution stage is now offered; design is not, because nothing has been validated.
    const solution = screen.getByRole("region", { name: "Solution validation" });
    expect(within(solution).getByRole("button", { name: "Validate solution" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
    expect(screen.getByText("HUMAN VALIDATED")).toBeInTheDocument();
    expect(mock).toHaveBeenCalledWith(expect.stringContaining("/api/interventions/diagnoses/hyp_1/propose"), expect.objectContaining({ method: "POST" }));
  });

  it("validates the solution, keeps the three reviews visually distinct, and gates design on the handoff", async () => {
    stored = interventionFixture("practice_simulation", null);
    const mock = route((path) => {
      if (path.endsWith("/validate-solution")) return reply(interventionFixture("practice_simulation", "aligned"));
      throw new Error(path);
    });
    render(<ReviewWorkspace />);
    await loaded();
    const solution = await screen.findByRole("region", { name: "Solution validation" });
    await userEvent.click(within(solution).getByRole("button", { name: "Validate solution" }));
    expect(await within(solution).findByText("Aligned")).toBeInTheDocument();
    expect(within(solution).getByText("SOLUTION VALIDATED")).toBeInTheDocument();
    expect(within(solution).getByText("Practice addresses the validated skill gap.")).toBeInTheDocument();
    expect(within(solution).getByText("Type fits the validated cause")).toBeInTheDocument();
    expect(within(solution).getByText(/Not a human decision, and not approval of training/)).toBeInTheDocument();
    expect(within(solution).getByText("0.7")).toBeInTheDocument();
    expect(within(solution).getByRole("note")).toHaveTextContent("Training design may proceed on this practice simulation proposal");
    // Three distinct regions: semantic evidence review, proposed intervention, solution validation.
    expect(screen.getByRole("region", { name: "Semantic evidence review" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Proposed intervention" })).toBeInTheDocument();
    expect(screen.getAllByText("HUMAN VALIDATED")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "DESIGN INTERVENTION" })).toBeInTheDocument();
    expect(screen.getByText(/drafts a training outline, activities, and practice/)).toBeInTheDocument();
    expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("withholds design when the solution review questions a training proposal", async () => {
    stored = interventionFixture("training", "misaligned", { humanRevised: true });
    route();
    render(<ReviewWorkspace />);
    await loaded();
    const solution = await screen.findByRole("region", { name: "Solution validation" });
    expect(await within(solution).findByText("Misaligned")).toBeInTheDocument();
    expect(within(solution).getByText("SOLUTION QUESTIONED")).toBeInTheDocument();
    expect(within(solution).getByText("What is not aligned")).toBeInTheDocument();
    expect(within(solution).getByText("Agent training does not correct a process gap")).toBeInTheDocument();
    expect(within(solution).getByText("Unsupported solution assumptions")).toBeInTheDocument();
    expect(within(solution).getByText("Frequency alone implies a training need")).toBeInTheDocument();
    expect(within(solution).getByRole("note")).toHaveTextContent("Training design is withheld");
    expect(screen.getByText(/nothing is handed to the M5 training generator/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
    expect(screen.getByText(/for the human-revised diagnosis Process Gap · Undetermined/)).toBeInTheDocument();
  });

  it("records a non-training decision without offering training", async () => {
    stored = interventionFixture("process_correction", "aligned", { fixture: true, reviewStatus: "evidence_questioned" });
    route();
    render(<ReviewWorkspace />);
    await loaded();
    const solution = await screen.findByRole("region", { name: "Solution validation" });
    expect(await within(solution).findByText("Aligned")).toBeInTheDocument();
    expect(within(solution).getByRole("note")).toHaveTextContent("does not call for training");
    expect(screen.getByText("Fixture confidence value", { selector: ".intervention-stage .field-label" })).toBeInTheDocument();
    expect(screen.getByText(/Fixed fixture proposal/)).toBeInTheDocument();
    expect(screen.getByText(/evidence review status: evidence questioned/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DESIGN INTERVENTION" })).toBeInTheDocument();
    expect(screen.getByText(/records the non-training decision in M5/)).toBeInTheDocument();
  });

  it("withholds M5 for a partially aligned training or non-training proposal", async () => {
    for (const type of ["training", "process_correction"] as const) {
      stored = interventionFixture(type, "partially_aligned");
      route();
      const view = render(<ReviewWorkspace />);
      await loaded();
      const solution = await screen.findByRole("region", { name: "Solution validation" });
      expect(within(solution).getByText("SOLUTION QUESTIONED")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
      expect(screen.getByText(/A corrected proposal needs a new diagnosis review run/)).toBeInTheDocument();
      view.unmount();
    }
  });

  it("opens the intervention's cited evidence in the inspector by local reference", async () => {
    stored = interventionFixture();
    route();
    render(<ReviewWorkspace />);
    await loaded();
    const panel = await screen.findByRole("region", { name: "Proposed intervention" });
    const cited = within(panel).getByRole("region", { name: "Evidence the intervention cites" });
    await userEvent.click(within(cited).getByRole("button", { name: /Evaluation eval_1/ }));
    expect(screen.getByText("No · Fail")).toBeInTheDocument();
    expect(screen.getByText("Next step unclear")).toBeInTheDocument();
  });

  it("shows truthful stage loading, ignores double clicks, and surfaces provider failures safely", async () => {
    let complete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { complete = resolve; });
    const mock = route(() => pending);
    render(<ReviewWorkspace />);
    await loaded();
    const button = screen.getByRole("button", { name: "Propose intervention" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.getByRole("status")).toHaveTextContent("Proposing intervention");
    complete(reply({ detail: { code: "invalid_intervention_output", message: "private provider text" } }, 502));
    expect(await screen.findByRole("alert")).toHaveTextContent("returned invalid output. No intervention was saved.");
    expect(screen.queryByText("private provider text")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Propose intervention" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Proposed intervention" })?.textContent).not.toContain("INTERVENTION PROPOSED ·");
    expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("refuses a malformed intervention record instead of rendering it", async () => {
    route(() => reply({ ...interventionFixture(), handoff: { training_design_gate: "approved" } }));
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Propose intervention" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected response");
    expect(screen.queryByText("INTERVENTION PROPOSED · NOT HUMAN VALIDATED")).not.toBeInTheDocument();
  });

  it("drops a stage that finishes after the reviewer switched to another hypothesis", async () => {
    const other: RecordState = { ...approved, provider_hypothesis: { ...approved.provider_hypothesis, hypothesis_id: "hyp_2", explanation: "Second proposal." } };
    let complete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { complete = resolve; });
    route(() => pending, [approved, other]);
    render(<ReviewWorkspace />);
    await loaded();
    fireEvent.click(screen.getByRole("button", { name: "Propose intervention" }));
    fireEvent.change(screen.getByLabelText("Review history"), { target: { value: "hyp_2" } });
    expect(await screen.findByText("Second proposal.")).toBeInTheDocument();
    complete(reply(interventionFixture()));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("INTERVENTION PROPOSED · NOT HUMAN VALIDATED")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("AWS-4 record guard and handoff text", () => {
  it("accepts coherent records and rejects incoherent ones", () => {
    for (const record of [interventionFixture(), interventionFixture("training", null), interventionFixture("coaching", "partially_aligned"),
      interventionFixture("investigate_further", "insufficient_evidence"), interventionFixture("practice_simulation", "misaligned")])
      expect(isInterventionRecord(record)).toBe(true);
    const base = interventionFixture();
    expect(isInterventionRecord({ ...base, status: "solution_questioned" })).toBe(false);
    expect(isInterventionRecord({ ...base, proposal: { ...base.proposal, intervention_type: "workshop" } })).toBe(false);
    expect(isInterventionRecord({ ...base, handoff: { ...base.handoff, human_reviewed_intervention: true } })).toBe(false);
    expect(isInterventionRecord({ ...base, handoff: { ...base.handoff, training_design_gate: "withheld" } })).toBe(false);
    expect(isInterventionRecord({ ...base, solution_validation: { ...base.solution_validation!, alignment_outcome: "misaligned" } })).toBe(false);
    expect(isInterventionRecord({ ...base, solution_validation: { ...base.solution_validation!, assessed: "diagnosis" } })).toBe(false);
    expect(isInterventionRecord({ ...base, validated_diagnosis: { ...base.validated_diagnosis, hypothesis_id: "hyp_9" } })).toBe(false);
    expect(isInterventionRecord({ ...interventionFixture("training", null), handoff: { ...base.handoff, solution_validation_id: null, solution_status: null, training_design_gate: "permitted" } })).toBe(false);
    expect(isInterventionRecord({ ...base, proposal: { ...base.proposal, provider_reported_confidence: "0.6" } })).toBe(false);
    expect(isInterventionRecord(null)).toBe(false);
    expect(isInterventionRecord("truncated")).toBe(false);
  });

  it("describes the gate as a lifecycle projection, never as approval", () => {
    for (const gate of ["permitted", "withheld", "not_applicable", "awaiting_solution_validation"] as const) {
      const text = gateText(gate, "training").toLowerCase();
      expect(text).not.toMatch(/approved training|human approved|validated training/);
    }
    expect(gateText("permitted", "practice_simulation")).toMatch(/a human has not approved it/);
    expect(gateText("withheld", "training")).toMatch(/nothing is handed to the training generator/);
    expect(gateText("not_applicable", "coaching")).toMatch(/does not call for training/);
  });
});

describe("M5 design summary with the AWS-4 handoff", () => {
  it("names the validated intervention and its solution review without calling it human validated", () => {
    const result = designFixture();
    result.intervention.intervention_type = "practice_simulation";
    result.intervention.solution_alignment = "aligned";
    result.intervention.intervention_id = "int_1";
    result.intervention.solution_validation_id = "sol_1";
    render(<DesignWorkspace result={result} />);
    expect(screen.getByText(/Solution-reviewed intervention: Practice Simulation · solution review Aligned/)).toBeInTheDocument();
    expect(screen.getByText("Not human validated")).toBeInTheDocument();
    expect(screen.getByText(/int_1 → solution review sol_1/)).toBeInTheDocument();
  });

  it("renders legacy results without the handoff line", () => {
    render(<DesignWorkspace result={designFixture()} />);
    expect(screen.queryByText(/Solution-reviewed intervention:/)).not.toBeInTheDocument();
  });
});
