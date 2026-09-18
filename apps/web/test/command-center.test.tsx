import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CommandCenter, { CommandCenterView, type ValidationControls } from "../app/command-center";
import type { EvidenceBundle, RecordState } from "../lib/diagnostics";
import { buildHomeReadModel } from "../lib/home/read-model";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";
import {
  alignmentReviewFixture,
  approved,
  awaiting,
  demoMode,
  fixtureRecord,
  insight,
  providerPackage,
  questionedReview,
  realMode,
  rejected,
  revisedApproved,
  revisedPending,
  secondSignal,
  sources,
  topSignal,
  validatedReview,
} from "./home.test-fixture";

const insightCard = (name = "Resolution clarity") => screen.getByRole("region", { name });
/** A labelled row inside the selected insight card (diagnosis trio and downstream rows). */
const field = (name: string) => {
  const labelNode = within(insightCard()).getByText(name, { selector: ".field-label" });
  return labelNode.parentElement as HTMLElement;
};
/** The AI evidence review block or the human validation block. */
const block = (name: "AI evidence review" | "Human validation", card = "Resolution clarity") =>
  within(insightCard(card)).getByText(name, { selector: ".field-label" }).closest(".review-block") as HTMLElement;
const pipelineStep = (name: string) => {
  const list = screen.getByRole("list", { name: "Progress of this insight through the workflow" });
  return within(list).getByText(name).parentElement as HTMLElement;
};
const decisionGroup = (card = "Resolution clarity") =>
  within(block("Human validation", card)).queryByRole("group", { name: "Human validation decision" });
const controlsFor = (record: RecordState | null, overrides: Partial<ValidationControls> = {}): ValidationControls => ({
  record,
  busy: false,
  error: null,
  onDecide: vi.fn(),
  loadBundle: vi.fn(async () => bundle),
  ...overrides,
});

const bundle: EvidenceBundle = {
  signal: topSignal,
  items: [
    {
      item_id: "ev_1", evaluation_id: "eval_1", domain: topSignal.domain, criterion: topSignal.criterion, passed: false,
      answer: "No", max_score: "10", attained_score: "2", evaluator_feedback: "Next step unclear",
      source_lineage: { source_filename: "synthetic.xlsx", source_sheet: "QA", excel_row: 2 },
    },
    {
      item_id: "ev_2", evaluation_id: "eval_2", domain: topSignal.domain, criterion: topSignal.criterion, passed: true,
      answer: "Yes", max_score: "10", attained_score: "10", evaluator_feedback: "Clear summary",
      source_lineage: { source_filename: "synthetic.xlsx", source_sheet: "QA", excel_row: 3 },
    },
  ],
};

/** Strings from the reference screenshot that have no backend support. None may render. */
const FABRICATED = /Sarah|24 Agents|\b78%|\b16\b Training|12% from|6% from|4 from last month|last month|Aug 1, 2026|Most Common Issue|Evaluation 7\b|Evaluation 11\b|Evaluation 14\b|did not explain the available options|Member seemed confused|proper resource/;
const FLASHCARDS = /Create Targeted Training|Practice with AI Role-Play|Track Improvement|Generate Training Plan|Start a Role-Play Session|improvement/i;

describe("Home decision dashboard from a typed read-model", () => {
  it("renders the real selected signal, the working diagnosis, and the three-column structure (A)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    expect(screen.getByRole("heading", { level: 1, name: /Here.s what needs attention/ })).toBeInTheDocument();
    const card = insightCard();
    expect(within(card).getByRole("heading", { level: 2, name: "Resolution clarity" })).toBeInTheDocument();
    expect(within(card).getByText("7 of 12")).toBeInTheDocument();
    expect(within(card).getByText(/criterion results failed \(58\.3% observed failure rate\) · 12 of 20 loaded evaluations/)).toBeInTheDocument();
    expect(within(card).getByText("Selected insight")).toBeInTheDocument();
    expect(within(card).getByText("AI proposal")).toBeInTheDocument();
    expect(within(card).getByText("Member Experience")).toBeInTheDocument();
    expect(within(field("Working root cause")).getByText("Skill Gap")).toBeInTheDocument();
    expect(within(field("Working root cause")).getByText("Agents close calls without confirming the next step.")).toBeInTheDocument();
    expect(within(field("Working root cause")).getByText(/does not select training/)).toBeInTheDocument();
    expect(within(field("Performance dimension")).getByText("Capability")).toBeInTheDocument();
    expect(within(field("Model-reported confidence")).getByText("0.78")).toBeInTheDocument();
    expect(within(field("Model-reported confidence")).getByText(/not a statistically calibrated probability/)).toBeInTheDocument();
    expect(within(field("Explanation")).getByText("Failed rows show summaries that omit the follow-up action.")).toBeInTheDocument();
    expect(within(card).queryByText(/priority insight|highest priority|most common/i)).not.toBeInTheDocument();
    // Left column: observed criteria in backend order, with a bar per criterion.
    const gaps = screen.getByRole("region", { name: "Performance gaps" });
    const rows = within(gaps).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByRole("button", { name: /Resolution clarity/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(rows[0]).getByRole("img", { name: "Observed failure rate 58.3%" })).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: /HIPAA verification/ })).toHaveAttribute("aria-pressed", "false");
    expect(within(gaps).getByText(/does not establish severity, priority, or cause/)).toBeInTheDocument();
    expect(within(gaps).queryByText(/priority ranking|top performance gaps/i)).not.toBeInTheDocument();
    // Right column: evidence counts and citations from the read-model.
    const evidence = screen.getByRole("region", { name: "Evidence from QA" });
    expect(within(evidence).getByText(/of 12 criterion results failed/)).toBeInTheDocument();
    expect(within(evidence).getByText(/rows carry evaluator feedback/)).toBeInTheDocument();
    expect(within(evidence).getByText("Evaluation eval_1")).toBeInTheDocument();
    expect(within(evidence).getByText("Aggregate QA signal")).toBeInTheDocument();
    expect(within(evidence).getByText("Evaluation eval_2")).toBeInTheDocument();
    expect(within(evidence).getByText("Observe a live call")).toBeInTheDocument();
    expect(within(evidence).getByText(/Evaluator feedback text is inspected row by row in Agent Insights/)).toBeInTheDocument();
    expect(within(evidence).queryByText("Next step unclear")).not.toBeInTheDocument();
    expect(pipelineStep("Human validated")).toHaveTextContent("Awaiting review");
  });

  it("shows every unsupported metric as Pending with only backend-loaded counts, never an invented number (B)", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    for (const name of ["Agents monitored", "Priority issues", "Overall QA", "Training / intervention"]) {
      const tile = screen.getByRole("article", { name });
      expect(tile.querySelector(".stat-value")).toHaveTextContent("Pending");
      expect(tile).not.toHaveTextContent(/%|from last month|\+\d/);
    }
    expect(within(screen.getByRole("article", { name: "Agents monitored" })).getByText("20 QA evaluations loaded")).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Priority issues" })).getByText(/backend has not classified or prioritized issues/)).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Training / intervention" })).getByText("Selected insight: awaiting human validation")).toBeInTheDocument();
    unmount();

    render(<CommandCenterView model={buildHomeReadModel(sources({ signals: [], priority: null, mode: null }))} />);
    expect(screen.getByText("No QA signals are loaded.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No observed criteria yet" })).toBeInTheDocument();
    for (const name of ["Agents monitored", "Priority issues", "Overall QA", "Training / intervention"]) {
      const tile = screen.getByRole("article", { name });
      expect(tile.querySelector(".stat-value")).toHaveTextContent("Pending");
      expect(tile.querySelector(".stat-note")).toBeNull();
      expect(tile.querySelector(".stat-detail")).not.toHaveTextContent(/\b\d+ (QA|evaluation|criteria|agent|issue)|\d+%|\d+\.\d/);
    }
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights");
  });

  it("offers Approve, Revise, and Reject as buttons on Home while the diagnosis awaits review (C)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} controls={controlsFor(awaiting)} />);
    const human = block("Human validation");
    expect(within(human).getByText("Awaiting review")).toHaveClass("pending");
    const group = decisionGroup()!;
    expect(group).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(within(group).getByRole("button", { name: "Revise" })).toHaveAttribute("aria-expanded", "false");
    expect(within(group).getByRole("button", { name: "Reject" })).toHaveAttribute("aria-expanded", "false");
    expect(within(human).queryByRole("tab")).not.toBeInTheDocument();
    expect(within(human).getByPlaceholderText("Your reviewer ID")).toBeInTheDocument();
    expect(screen.getByText("AI checks the evidence. A human makes the consequential decision.")).toBeInTheDocument();
  });

  it("requires a reviewer identifier before recording any decision, without inventing one", async () => {
    const controls = controlsFor(awaiting);
    render(<CommandCenterView model={buildHomeReadModel(sources())} controls={controls} />);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(controls.onDecide).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your reviewer ID to record a decision.");
    expect(screen.getByPlaceholderText("Your reviewer ID")).toHaveFocus();
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-lead");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(controls.onDecide).toHaveBeenCalledWith({ kind: "approve", reviewer: "qa-lead" });
  });

  it("removes every mutation action once the decision is approved (I)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved }) }))} controls={controlsFor(approved)} />);
    const human = block("Human validation");
    expect(within(human).getByText("Approved")).toHaveClass("validated");
    expect(within(human).getByText(/Recorded by qa-lead/)).toBeInTheDocument();
    expect(within(human).getByText(/human decision on the diagnosis, not on any intervention/)).toBeInTheDocument();
    expect(decisionGroup()).toBeNull();
    expect(within(insightCard()).queryByRole("button", { name: /approve|revise|reject/i })).not.toBeInTheDocument();
    expect(within(insightCard()).queryByPlaceholderText("Your reviewer ID")).not.toBeInTheDocument();
    expect(pipelineStep("Human validated")).toHaveTextContent("Approved");
    // Approval of the diagnosis is not an intervention, solution, or training state.
    expect(within(field("Intervention")).getByText("Not proposed")).toBeInTheDocument();
    expect(within(field("Solution validation")).getByText("Not applicable yet")).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(insightCard()).getByText("Generate intervention")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("shows the human revision as the authoritative diagnosis, with only its approval still open (J)", () => {
    const view = render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: revisedPending }) }))} controls={controlsFor(revisedPending)} />);
    expect(within(insightCard()).getByText("Human-revised diagnosis")).toBeInTheDocument();
    expect(within(field("Working root cause")).getByText("Process Gap")).toBeInTheDocument();
    expect(within(field("Performance dimension")).getByText("Undetermined")).toBeInTheDocument();
    expect(within(field("Explanation")).getByText("Reviewer found a process issue.")).toBeInTheDocument();
    const human = block("Human validation");
    expect(within(human).getByText("Revised · awaiting approval")).toHaveClass("caution");
    expect(within(human).getByText(/correction by qa-2 is now the authoritative working diagnosis/)).toBeInTheDocument();
    expect(within(human).getByText("Process evidence")).toBeInTheDocument();
    expect(within(human).getByRole("button", { name: "Approve human revision" })).toBeInTheDocument();
    expect(within(human).queryByRole("button", { name: "Revise" })).not.toBeInTheDocument();
    expect(within(human).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(pipelineStep("Diagnosed")).toHaveTextContent("Human revised");
    expect(pipelineStep("Human validated")).toHaveTextContent("Revision awaiting approval");
    view.unmount();

    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: revisedApproved }) }))} controls={controlsFor(revisedApproved)} />);
    expect(within(block("Human validation")).getByText("Revised · approved")).toHaveClass("validated");
    expect(within(block("Human validation")).getByText(/human-revised diagnosis is approved and authoritative/)).toBeInTheDocument();
    expect(decisionGroup()).toBeNull();
    expect(within(field("Working root cause")).getByText("Process Gap")).toBeInTheDocument();
  });

  it("shows a rejected decision with every downstream stage blocked and no actions (K)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: rejected }) }))} controls={controlsFor(rejected)} />);
    const human = block("Human validation");
    expect(within(human).getByText("Rejected")).toHaveClass("rejected");
    expect(within(human).getByText(/rejected by qa-3\. Downstream stages are blocked/)).toBeInTheDocument();
    expect(within(human).getByText("Evidence too thin")).toBeInTheDocument();
    expect(decisionGroup()).toBeNull();
    expect(within(insightCard()).queryByRole("button", { name: /approve|revise|reject/i })).not.toBeInTheDocument();
    expect(pipelineStep("Human validated")).toHaveClass("rejected");
    expect(pipelineStep("Intervention proposed")).toHaveTextContent("Blocked");
    expect(pipelineStep("Training generated")).toHaveTextContent("Blocked");
    expect(pipelineStep("Alignment")).toHaveTextContent("Blocked");
    expect(within(field("Intervention")).getByText("Requires human-validated diagnosis")).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(field("Alignment review")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(insightCard()).getByText("Request another hypothesis")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("keeps the AI evidence review separate from the human decision in both directions (L)", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ validation: validatedReview }) }))} controls={controlsFor(awaiting)} />);
    const ai = block("AI evidence review");
    expect(within(ai).getByText("Evidence validated · Supported")).toHaveClass("validated");
    expect(within(ai).getByText("The cited rows show the missing next-step summary.")).toBeInTheDocument();
    expect(within(ai).getByText(/Not a human decision/)).toBeInTheDocument();
    expect(within(block("Human validation")).getByText("Awaiting review")).toBeInTheDocument();
    expect(decisionGroup()).toBeInTheDocument();
    expect(pipelineStep("Evidence reviewed")).toHaveClass("validated");
    expect(pipelineStep("Human validated")).toHaveClass("pending");
    unmount();

    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ validation: questionedReview }) }))} controls={controlsFor(awaiting)} />);
    const questioned = within(block("AI evidence review")).getByText("Evidence questioned · Unsupported");
    expect(questioned).toHaveClass("caution");
    expect(questioned).not.toHaveClass("rejected");
    expect(within(block("AI evidence review")).getByText(/1 claim beyond the evidence · 1 evidence gap noted/)).toBeInTheDocument();
    expect(within(block("Human validation")).getByText("Awaiting review")).toBeInTheDocument();
    expect(decisionGroup()).toBeInTheDocument();
    expect(screen.queryByText(/^Rejected$/)).not.toBeInTheDocument();

    // And an approved diagnosis never rewrites the AI verdict.
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, validation: questionedReview }) }))} />);
  });

  it("shows a proposed AWS-4 intervention with solution validation pending", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", null) }) }))} />);
    expect(within(field("Intervention")).getByText("Training proposed · solution not validated")).toHaveClass("proposed");
    expect(within(field("Intervention")).getByText("Rehearse the closing summary in short simulated calls.")).toBeInTheDocument();
    expect(within(field("Intervention")).getByText(/Target change: State the next step/)).toBeInTheDocument();
    expect(within(field("Solution validation")).getByText("Awaiting validation")).toBeInTheDocument();
    expect(within(insightCard()).getByText("Validate solution")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(pipelineStep("Intervention proposed")).toHaveTextContent("Training");
    expect(pipelineStep("Solution validated")).toHaveTextContent("Awaiting validation");
  });

  it("shows a solution-validated training intervention as permitted, not generated, and never as alignment", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "aligned") }) }))} />);
    expect(within(field("Intervention")).getByText("Training · solution validated")).toHaveClass("validated");
    expect(within(field("Solution validation")).getByText("Solution validated · Aligned")).toHaveClass("validated");
    expect(within(field("Solution validation")).getByText(/Not a human approval, and not training alignment/)).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Ready to generate · not generated")).toHaveClass("pending");
    expect(within(field("Alignment review")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(insightCard()).getByText("Generate training")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("shows a validated process correction with training not applicable, not failed (M)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("process_correction", "aligned"), design: designFixture("non_training") }) }))} />);
    expect(within(field("Intervention")).getByText("Process Correction · solution validated")).toHaveClass("validated");
    const training = within(field("Training package")).getByText("Training not applicable");
    expect(training).toHaveClass("not_applicable");
    expect(training).not.toHaveClass("caution");
    expect(within(field("Training package")).getByText(/does not call for training, so no package is generated/)).toBeInTheDocument();
    expect(pipelineStep("Training generated")).toHaveTextContent("Not applicable");
    expect(pipelineStep("Alignment")).toHaveTextContent("Not applicable");
    expect(within(field("Alignment review")).getByText("Not applicable")).toHaveClass("not_applicable");
    expect(within(insightCard()).getByText("Review validated process intervention")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.queryByText(/withheld|failed training/i)).not.toBeInTheDocument();
  });

  it("shows a questioned solution as caution with training withheld (N)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "misaligned") }) }))} />);
    const solution = within(field("Solution validation")).getByText("Solution questioned · Misaligned");
    expect(solution).toHaveClass("caution");
    expect(solution).not.toHaveClass("rejected");
    expect(within(field("Solution validation")).getByText(/Training does not address the validated cause/)).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Training withheld")).toHaveClass("caution");
    expect(pipelineStep("Solution validated")).toHaveTextContent("Questioned");
    expect(pipelineStep("Training generated")).toHaveTextContent("Withheld");
    expect(within(insightCard()).getByText("Review solution concerns")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.queryByText(/^Rejected$/)).not.toBeInTheDocument();
  });

  it("shows a generated AWS-5 package as generated, not deployed, with alignment pending (O)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage() }) }))} />);
    expect(within(field("Training package")).getByText("Training generated · not deployed")).toHaveClass("validated");
    expect(within(field("Training package")).getByText("State next step and check understanding")).toBeInTheDocument();
    expect(within(field("Training package")).getByText(/1 outline section · 1 activity · 1 knowledge check · 1 practice scenario · 12 min planned · 1 operational detail still needed/)).toBeInTheDocument();
    expect(within(field("Training package")).getByRole("link", { name: "Open training package" })).toHaveAttribute("href", "/training?signal=sig_top");
    expect(within(field("Training package")).getByRole("link", { name: "Open role-play script" })).toHaveAttribute("href", "/role-play?signal=sig_top");
    expect(within(field("Alignment review")).getByText("Pending · not yet reviewed")).toHaveClass("pending");
    expect(within(field("Alignment review")).getByText(/has not been run/)).toBeInTheDocument();
    expect(pipelineStep("Training generated")).toHaveTextContent("Generated");
    expect(pipelineStep("Alignment")).toHaveTextContent("Pending");
    expect(within(insightCard()).getByText("Review training alignment")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(field("Outcome")).getByText("Measurement pending")).toHaveClass("pending");
    expect(within(field("Outcome")).getByRole("link", { name: "Open KPI Tracker" })).toHaveAttribute("href", "/kpi-tracker");
    expect(within(field("Outcome")).queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/improve/i)).not.toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Training / intervention" })).getByText("Selected insight: training package generated, alignment pending")).toBeInTheDocument();
  });

  it("shows an AWS-6 aligned review as Design aligned, distinct from solution and outcome states (P)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage(), alignment: alignmentReviewFixture("aligned") }) }))} />);
    const alignment = field("Alignment review");
    expect(within(alignment).getByText("Design aligned · Aligned")).toHaveClass("validated");
    expect(within(alignment).getByText("The package trains the confirmed closing behavior.")).toBeInTheDocument();
    expect(within(alignment).getByText(/0 problematic elements · 0 unsupported assumptions · 0 missing information items/)).toBeInTheDocument();
    expect(within(alignment).getByText(/Validator-reported confidence 0\.8; Validator self-report for this review\. It is not a statistically calibrated probability\./)).toBeInTheDocument();
    expect(within(alignment).getByText(/Independent AI semantic review of the package against the confirmed gap\. Not a human decision, not deployment, and not an outcome\./)).toBeInTheDocument();
    expect(within(block("Human validation")).getByText("Approved")).toBeInTheDocument();
    expect(within(field("Solution validation")).getByText(/Solution validated · Aligned/)).toHaveClass("validated");
    expect(within(field("Training package")).getByText("Training generated · not deployed")).toBeInTheDocument();
    expect(pipelineStep("Human validated")).toHaveTextContent("Approved");
    expect(pipelineStep("Solution validated")).toHaveTextContent("Validated");
    expect(pipelineStep("Training generated")).toHaveTextContent("Generated");
    expect(pipelineStep("Alignment")).toHaveTextContent("Design aligned");
    expect(pipelineStep("Alignment")).toHaveClass("validated");
    expect(within(insightCard()).getByText("Review aligned training package")).toHaveAttribute("href", "/training?signal=sig_top");
    expect(within(field("Outcome")).getByText("Measurement pending")).toBeInTheDocument();
    expect(screen.getByText("Selected insight: training package generated, design aligned")).toBeInTheDocument();
    expect(screen.queryByText(/outcome validated|improv|effective|has been deployed/i)).not.toBeInTheDocument();
  });

  it.each([
    ["partially_aligned", "Partially Aligned"],
    ["misaligned", "Misaligned"],
    ["insufficient_information", "Insufficient Information"],
  ] as const)("shows a %s review as Design questioned in caution tone with a concerns route (Q)", (outcome, outcomeLabel) => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage(), alignment: alignmentReviewFixture(outcome) }) }))} />);
    const alignment = field("Alignment review");
    expect(within(alignment).getByText(`Design questioned · ${outcomeLabel}`)).toHaveClass("caution");
    expect(within(alignment).getByText(/1 problematic element · 1 unsupported assumption · (0|1) missing information items?/)).toBeInTheDocument();
    expect(pipelineStep("Alignment")).toHaveTextContent("Design questioned");
    expect(pipelineStep("Alignment")).toHaveClass("caution");
    expect(pipelineStep("Alignment")).not.toHaveClass("rejected");
    expect(within(insightCard()).getByText("Review alignment concerns")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(field("Solution validation")).getByText(/Solution validated · Aligned/)).toHaveClass("validated");
    expect(within(field("Training package")).getByText("Training generated · not deployed")).toBeInTheDocument();
    expect(screen.getByText("Selected insight: training package generated, design questioned")).toBeInTheDocument();
    expect(screen.queryByText(/rejected/i)).not.toBeInTheDocument();
  });

  it("never renders a stale review, a review for a process correction, or one for a questioned solution", () => {
    const stale = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage(), alignment: alignmentReviewFixture("aligned", { run_id: "design_0" }) }) }));
    const view = render(<CommandCenterView model={stale} />);
    expect(within(field("Alignment review")).getByText("Pending · not yet reviewed")).toBeInTheDocument();
    expect(screen.queryByText(/Design aligned/)).not.toBeInTheDocument();

    view.rerender(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("process_correction", "aligned"), design: designFixture("non_training"), alignment: alignmentReviewFixture("aligned") }) }))} />);
    expect(within(field("Alignment review")).getByText("Not applicable")).toHaveClass("not_applicable");
    expect(within(field("Training package")).getByText("Training not applicable")).toBeInTheDocument();
    expect(screen.queryByText(/Design aligned/)).not.toBeInTheDocument();

    view.rerender(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "misaligned"), design: providerPackage(), alignment: alignmentReviewFixture("aligned") }) }))} />);
    expect(within(field("Alignment review")).getByText("Blocked upstream")).toHaveClass("neutral");
    expect(within(field("Training package")).getByText("Training withheld")).toHaveClass("caution");
    expect(screen.queryByText(/Design aligned/)).not.toBeInTheDocument();
  });

  it("renders no value, name, quote, or date range copied from the reference screenshot (R)", () => {
    const states = [
      sources(),
      sources({ mode: demoMode, priority: insight({ record: fixtureRecord }) }),
      sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage(), alignment: alignmentReviewFixture("aligned") }) }),
      sources({ signals: [], priority: null, mode: null }),
    ];
    for (const state of states) {
      const view = render(<CommandCenterView model={buildHomeReadModel(state)} controls={controlsFor(state.priority?.record ?? null)} />);
      expect(document.body.textContent).not.toMatch(FABRICATED);
      expect(document.body.textContent).not.toMatch(/Good morning, Sarah/);
      view.unmount();
    }
  });

  it("ends after the dashboard: no bottom flashcard row and no separate downstream card grid (S)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage() }) }))} />);
    expect(document.body.textContent).not.toMatch(FLASHCARDS);
    expect(screen.queryByRole("region", { name: "Intervention, training, alignment, outcome" })).not.toBeInTheDocument();
    const main = screen.getByRole("main");
    const sections = main.querySelectorAll(":scope > .home-grid > section");
    expect(sections).toHaveLength(3);
    expect(main.lastElementChild).toHaveClass("home-grid");
  });

  it("keeps Agent Insights as the deep-dive route from the card, the gaps list, and the evidence panel (T)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ signal: secondSignal, record: null }) }))} />);
    const cta = screen.getByRole("link", { name: "View full evidence in Agent Insights" });
    expect(cta).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(cta).toHaveClass("primary");
    expect(screen.getByText("Review observed evidence and run diagnosis")).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(screen.getByRole("link", { name: /View all 3 observed criteria/ })).toHaveAttribute("href", "/agent-insights");
    expect(within(screen.getByRole("region", { name: "Evidence from QA" })).getByRole("link", { name: /View all/ })).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(pipelineStep("Diagnosed")).toHaveTextContent("Not requested");
    expect(within(insightCard("HIPAA verification")).getByText("No diagnosis requested")).toBeInTheDocument();
    expect(within(insightCard("HIPAA verification")).getByText("Observed only · no diagnosis yet")).toBeInTheDocument();
    expect(within(block("Human validation", "HIPAA verification")).getByText("No diagnosis to validate")).toBeInTheDocument();
    expect(decisionGroup("HIPAA verification")).toBeNull();
  });

  it("separates synthetic demo provenance from real ResultsCX provenance", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources({ mode: demoMode, priority: insight({ record: fixtureRecord }) }))} />);
    const badge = screen.getByRole("note", { name: "Data provenance" });
    expect(within(badge).getByText("Synthetic demo")).toBeInTheDocument();
    expect(within(badge).getByText(/Nothing here is ResultsCX output/)).toBeInTheDocument();
    expect(within(badge).getByText(/Intervention provider: controlled_fixture/)).toBeInTheDocument();
    expect(within(insightCard()).getByText("Controlled non-AI fixture proposal")).toBeInTheDocument();
    expect(within(field("Fixture confidence value")).getByText(/No model reported it/)).toBeInTheDocument();
    unmount();

    render(<CommandCenterView model={buildHomeReadModel(sources({ mode: realMode }))} />);
    const real = screen.getByRole("note", { name: "Data provenance" });
    expect(within(real).getByText("Real ResultsCX · local")).toBeInTheDocument();
    expect(within(real).queryByText(/Synthetic/)).not.toBeInTheDocument();
    expect(screen.queryByText(/fixture/i)).not.toBeInTheDocument();
  });
});

function reply(value: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => value } as Response;
}

type Backend = {
  records?: Record<string, RecordState[]>;
  intervention?: unknown;
  design?: unknown;
  alignment?: unknown;
  signals?: unknown[];
  mode?: unknown;
  mutation?: (path: string, init?: RequestInit) => Promise<Response>;
};

/** A stubbed backend whose record store the tests can mutate between requests. */
function route(backend: Backend = {}) {
  const state = {
    records: backend.records ?? { sig_top: [awaiting], sig_second: [] },
    intervention: backend.intervention ?? null,
    design: backend.design ?? null,
    alignment: backend.alignment ?? null,
    signals: backend.signals ?? [topSignal, secondSignal],
    mode: backend.mode ?? realMode,
  };
  const mock = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      if (backend.mutation) return backend.mutation(path, init);
      throw new Error(`Unexpected mutation ${path}`);
    }
    if (path.endsWith("/mode")) return reply(state.mode);
    if (path.endsWith("/signals")) return reply(state.signals);
    if (path.endsWith("/review-evidence")) return reply(bundle);
    const hypotheses = path.match(/\/signals\/([^/]+)\/hypotheses$/);
    if (hypotheses) return reply(state.records[hypotheses[1]] ?? []);
    if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
    if (path.includes("/interventions/")) return state.intervention ? reply(state.intervention) : reply({ detail: { code: "intervention_not_found" } }, 404);
    if (path.endsWith("/alignment-review")) return state.alignment ? reply(state.alignment) : reply({ detail: { code: "alignment_review_not_found" } }, 404);
    if (path.includes("/designs/")) return state.design ? reply(state.design) : reply({ detail: { code: "design_not_found" } }, 404);
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return { mock, state };
}
const posts = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");

describe("Home data states and M4 decisions against the backend", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows loading, then renders real backend data with the decision controls", async () => {
    route();
    render(<CommandCenter />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading team summary");
    expect(await screen.findByRole("region", { name: "Resolution clarity" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View full evidence in Agent Insights" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.getByText("Real ResultsCX · local")).toBeInTheDocument();
    expect(decisionGroup()).toBeInTheDocument();
  });

  it("approves through the existing M4 endpoint and reloads Home from the backend (D)", async () => {
    const { mock, state } = route({
      mutation: async (path, init) => {
        expect(path).toBe("/api/diagnostics/hypotheses/hyp_1/approve");
        expect(JSON.parse(String(init?.body))).toEqual({ reviewer_id: "qa-lead" });
        state.records = { ...state.records, sig_top: [approved] };
        return reply(approved);
      },
    });
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-lead");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await within(block("Human validation")).findByText("Approved")).toHaveClass("validated");
    expect(posts(mock)).toHaveLength(1);
    expect(decisionGroup()).toBeNull();
    expect(pipelineStep("Human validated")).toHaveTextContent("Approved");
    // Downstream remains whatever the backend reports: nothing was proposed yet.
    expect(within(field("Intervention")).getByText("Not proposed")).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(screen.getByText("Generate intervention")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    // The reload re-read the record list rather than trusting the response alone.
    const reads = mock.mock.calls.filter(([path]) => String(path).endsWith("/sig_top/hypotheses"));
    expect(reads.length).toBeGreaterThanOrEqual(2);
  });

  it("rejects through the existing M4 endpoint with the reviewer's rationale and shows downstream blocked (E)", async () => {
    const { mock, state } = route({
      mutation: async (path, init) => {
        expect(path).toBe("/api/diagnostics/hypotheses/hyp_1/reject");
        expect(JSON.parse(String(init?.body))).toEqual({ reviewer_id: "qa-3", rationale: "Evidence too thin" });
        state.records = { ...state.records, sig_top: [rejected] };
        return reply(rejected);
      },
    });
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-3");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(posts(mock)).toHaveLength(0);
    await userEvent.type(screen.getByLabelText("Reason for rejection"), "Evidence too thin");
    await userEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));
    expect(await within(block("Human validation")).findByText("Rejected")).toHaveClass("rejected");
    expect(posts(mock)).toHaveLength(1);
    expect(within(block("Human validation")).getByText(/Downstream stages are blocked/)).toBeInTheDocument();
    expect(pipelineStep("Intervention proposed")).toHaveTextContent("Blocked");
    expect(decisionGroup()).toBeNull();
    expect(screen.getByText("Request another hypothesis")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("opens the revision form inline on Home without navigating away (F)", async () => {
    const { mock } = route();
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-2");
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    const form = await within(insightCard()).findByRole("heading", { name: "Revise diagnosis" });
    expect(form).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revise" })).toHaveAttribute("aria-expanded", "true");
    expect(window.location.pathname).toBe("/");
    expect(mock).toHaveBeenCalledWith("/api/diagnostics/signals/sig_top/review-evidence", expect.anything());
    // Every citation of this signal can be re-related, exactly as in Agent Insights.
    expect(screen.getByLabelText("Evidence relationship for signal")).toHaveValue("supporting");
    expect(screen.getByLabelText("Evidence relationship for ev_1")).toHaveValue("supporting");
    expect(screen.getByLabelText("Evidence relationship for ev_2")).toHaveValue("conflicting");
    expect(screen.getByLabelText("Corrected cause")).toHaveValue("skill_gap");
    expect(screen.getByRole("main")).toContainElement(screen.getByRole("button", { name: "Save revision" }));
    expect(posts(mock)).toHaveLength(0);
  });

  it("submits the exact existing M4 revision contract and shows the revision as authoritative (G)", async () => {
    const revision = {
      ...awaiting.provider_hypothesis,
      cause_domain: "process_gap",
      explanation: "Reviewer found a process issue.",
      conflicting_evidence: [],
      supporting_evidence: [
        { item_id: "ev_1", evaluation_id: "eval_1" },
        { item_id: "signal", evaluation_id: null },
        { item_id: "ev_2", evaluation_id: "eval_2" },
      ],
    };
    const { mock, state } = route({
      mutation: async (path, init) => {
        expect(path).toBe("/api/diagnostics/hypotheses/hyp_1/revise");
        const sent = JSON.parse(String(init?.body));
        expect(Object.keys(sent).sort()).toEqual(["rationale", "reviewer_id", "revision"]);
        expect(sent.reviewer_id).toBe("qa-2");
        expect(sent.rationale).toBe("Process evidence");
        expect(Object.keys(sent.revision).sort()).toEqual([
          "cause_domain", "conflicting_evidence", "explanation", "missing_evidence",
          "observed_behavioral_defect", "performance_dimension", "supporting_evidence",
        ]);
        expect(sent.revision.cause_domain).toBe("process_gap");
        expect(sent.revision.performance_dimension).toBe("capability");
        expect(sent.revision.explanation).toBe("Reviewer found a process issue.");
        expect(sent.revision.observed_behavioral_defect).toBe(awaiting.provider_hypothesis.observed_behavioral_defect);
        expect(sent.revision.missing_evidence).toEqual(["Observe a live call"]);
        expect(sent.revision.supporting_evidence).toEqual([
          { item_id: "ev_1", evaluation_id: "eval_1" },
          { item_id: "signal", evaluation_id: null },
          { item_id: "ev_2", evaluation_id: "eval_2" },
        ]);
        expect(sent.revision.conflicting_evidence).toEqual([]);
        const stored: RecordState = {
          ...awaiting, status: "revised", human_revision: revision,
          events: [{ action: "revise", reviewer_id: "qa-2", occurred_at: "2026-09-17T12:00:00Z", rationale: "Process evidence" }],
        };
        state.records = { ...state.records, sig_top: [stored] };
        return reply(stored);
      },
    });
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-2");
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    await within(insightCard()).findByRole("heading", { name: "Revise diagnosis" });
    fireEvent.change(screen.getByLabelText("Corrected cause"), { target: { value: "process_gap" } });
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "Reviewer found a process issue." } });
    fireEvent.change(screen.getByLabelText("Evidence relationship for ev_2"), { target: { value: "supporting" } });
    await userEvent.type(screen.getByLabelText("Reason for revision"), "Process evidence");
    await userEvent.click(screen.getByRole("button", { name: "Save revision" }));
    expect(await within(block("Human validation")).findByText("Revised · awaiting approval")).toHaveClass("caution");
    expect(posts(mock)).toHaveLength(1);
    expect(within(insightCard()).queryByRole("heading", { name: "Revise diagnosis" })).not.toBeInTheDocument();
    expect(within(insightCard()).getByText("Human-revised diagnosis")).toBeInTheDocument();
    expect(within(field("Working root cause")).getByText("Process Gap")).toBeInTheDocument();
    expect(within(field("Explanation")).getByText("Reviewer found a process issue.")).toBeInTheDocument();
    expect(within(block("Human validation")).getByRole("button", { name: "Approve human revision" })).toBeInTheDocument();
    expect(screen.getByText("Approve human revision", { selector: ".next-step a" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(pipelineStep("Human validated")).toHaveTextContent("Revision awaiting approval");
    // AWS-4 consumes the backend record; Home did not promote the revision into a validated state.
    expect(within(field("Intervention")).getByText("Requires human-validated diagnosis")).toBeInTheDocument();
  });

  it("cancelling a revision or a rejection makes no mutation and keeps the record unchanged (H)", async () => {
    const { mock } = route();
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-2");
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    await within(insightCard()).findByRole("heading", { name: "Revise diagnosis" });
    fireEvent.change(screen.getByLabelText("Corrected explanation"), { target: { value: "Changed but not saved" } });
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(within(insightCard()).queryByRole("heading", { name: "Revise diagnosis" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revise" })).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    await userEvent.type(screen.getByLabelText("Reason for rejection"), "Not saved");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Reason for rejection")).not.toBeInTheDocument();
    expect(posts(mock)).toHaveLength(0);
    expect(within(block("Human validation")).getByText("Awaiting review")).toBeInTheDocument();
    expect(within(field("Explanation")).getByText("Failed rows show summaries that omit the follow-up action.")).toBeInTheDocument();
    expect(screen.queryByText("Changed but not saved")).not.toBeInTheDocument();
  });

  it("keeps the proposed state on a failed decision and re-reads the record on a 409", async () => {
    const { state } = route({
      mutation: async () => {
        state.records = { ...state.records, sig_top: [approved] };
        return reply({ detail: { code: "invalid_state_transition", message: "Internal secret" } }, 409);
      },
    });
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-lead");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Decision not recorded");
    expect(alert).toHaveTextContent("This review changed or can no longer accept that action.");
    expect(alert).not.toHaveTextContent("Internal secret");
    // The backend's current state was re-read after the conflict.
    expect(await within(block("Human validation")).findByText("Approved")).toBeInTheDocument();
  });

  it("changes the selected insight from the performance gaps list and never carries state across signals", async () => {
    route({ records: { sig_top: [approved], sig_second: [] }, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage(), alignment: alignmentReviewFixture("aligned") });
    render(<CommandCenter />);
    expect(await screen.findByText("Design aligned · Aligned")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /HIPAA verification/ }));
    expect(await screen.findByRole("region", { name: "HIPAA verification" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /HIPAA verification/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Resolution clarity/ })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByText("Design aligned · Aligned")).not.toBeInTheDocument();
    expect(screen.queryByText(/The package trains the confirmed closing behavior/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View full evidence in Agent Insights" })).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(within(block("Human validation", "HIPAA verification")).getByText("No diagnosis to validate")).toBeInTheDocument();
    expect(decisionGroup("HIPAA verification")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Resolution clarity/ }));
    expect(await screen.findByText("Design aligned · Aligned")).toBeInTheDocument();
  });

  it("removes the previous signal's actions and evidence while another gap loads", async () => {
    const { mock } = route();
    const backendFetch = globalThis.fetch;
    let finishSecond!: (response: Response) => void;
    const secondRecord = new Promise<Response>((resolve) => { finishSecond = resolve; });
    vi.stubGlobal("fetch", vi.fn((path: string, init?: RequestInit) =>
      path.endsWith("/sig_second/hypotheses") ? secondRecord : backendFetch(path, init),
    ));
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-lead");
    await userEvent.click(screen.getByRole("button", { name: /HIPAA verification/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading team summary");
    expect(screen.queryByRole("region", { name: "Resolution clarity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Evidence from QA" })).not.toBeInTheDocument();
    expect(posts(mock)).toHaveLength(0);
    finishSecond(reply([]));
    expect(await screen.findByRole("region", { name: "HIPAA verification" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View full evidence in Agent Insights" })).toHaveAttribute("href", "/agent-insights?signal=sig_second");
  });

  it("does not offer revision when evidence references belong to another signal", async () => {
    const controls = controlsFor(awaiting, {
      reviewer: "qa-lead",
      loadBundle: vi.fn(async () => ({ ...bundle, signal: secondSignal })),
    });
    render(<CommandCenterView model={buildHomeReadModel(sources())} controls={controls} />);
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Source evidence references could not be loaded");
    expect(screen.queryByRole("button", { name: "Save revision" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry references" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(controls.onDecide).not.toHaveBeenCalled();
  });

  it("opens on a deep-linked signal and falls back with a notice when it is unknown", async () => {
    const { unmount } = render(<CommandCenter initialSignalId="sig_second" />);
    route();
    expect(await screen.findByRole("region", { name: "HIPAA verification" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    unmount();

    route();
    render(<CommandCenter initialSignalId="sig_missing" />);
    expect(await screen.findByRole("region", { name: "Resolution clarity" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Requested signal is unavailable.");
  });

  it("reloads the read-model from the backend on refresh, picking up AWS-4 and AWS-6 state", async () => {
    const { state } = route({ mode: demoMode, signals: [topSignal] });
    render(<CommandCenter />);
    await screen.findByRole("region", { name: "Resolution clarity" });
    expect(within(block("Human validation")).getByText("Awaiting review")).toBeInTheDocument();
    state.records = { sig_top: [approved] };
    state.intervention = interventionFixture("training", "aligned", { fixture: true });
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await within(block("Human validation")).findByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Training · solution validated")).toBeInTheDocument();
    expect(screen.getByText("Generate training")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.queryByText("Awaiting review")).not.toBeInTheDocument();
    state.intervention = interventionFixture("practice_simulation", "aligned");
    state.design = providerPackage();
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Pending · not yet reviewed", { selector: ".insight-field .pill" })).toBeInTheDocument();
    state.alignment = alignmentReviewFixture("aligned");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Design aligned · Aligned")).toBeInTheDocument();
    expect(screen.getByText("Review aligned training package")).toHaveAttribute("href", "/training?signal=sig_top");
  });

  it("shows an error with a retry and a route into Agent Insights when the service is unavailable", async () => {
    const mock = vi.fn<(path: string) => Promise<Response>>(async () => { throw new TypeError("network"); });
    vi.stubGlobal("fetch", mock);
    render(<CommandCenter />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Team summary unavailable");
    expect(alert).toHaveTextContent("The diagnostic service is unavailable.");
    expect(within(alert).getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights");
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+ of \d+/)).not.toBeInTheDocument();
    mock.mockImplementation(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([]);
      throw new Error(`Unexpected route ${path}`);
    });
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No QA signals are loaded.")).toBeInTheDocument();
  });
});
