import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DesignWorkspace from "../app/design-workspace";
import { isDesignResult } from "../lib/designs";
import { designFixture } from "./design-workspace.test-fixture";

describe("M5 result presentation", () => {
  it("leads with status, human readable behavior, and a complete learning sequence", () => {
    const result = designFixture();
    expect(isDesignResult(result)).toBe(true);
    render(<DesignWorkspace result={result} />);
    expect(screen.getByText("CONTROLLED NON-AI DEMO PROPOSAL")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("READY FOR ALIGNMENT REVIEW");
    expect(screen.getByText("Missed clarity")).toBeInTheDocument();
    expect(screen.getByText("State next step and check understanding")).toHaveClass("target-statement");
    expect(screen.getByText("Summarize and confirm on a simulated call")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Learning plan" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Model and rehearse" })).toBeInTheDocument();
    expect(screen.getByText("Show and practice")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What the learner will do" })).toBeInTheDocument();
    expect(screen.getByText("Summarize and check")).toBeInTheDocument();
    expect(screen.getByText("Member confirms", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Morgan")).toBeInTheDocument();
    expect(screen.getByText("“What happens next?”")).toBeInTheDocument();
    expect(screen.getByText("Summarize and confirm")).toBeInTheDocument();
    expect(screen.getByText("Clear next step and check")).toBeInTheDocument();
    expect(screen.getByText("No learner has been scored.")).toBeInTheDocument();
  });

  it("uses the selected observed QA criterion in the design summary", () => {
    render(<DesignWorkspace result={designFixture()} signalLabel="Resolution summary clarity" />);
    expect(screen.getByText("Resolution summary clarity")).toHaveClass("design-problem");
    expect(screen.getByText("Missed clarity")).toHaveClass("design-observation");
  });

  it("keeps full IDs and structural provenance in a trace affordance", () => {
    render(<DesignWorkspace result={designFixture()} />);
    const trace = screen.getByText("View trace, evidence & provenance").closest("details")!;
    expect(trace).not.toHaveAttribute("open");
    expect(screen.getByText(/Design origin: Controlled non-AI fixture/, { selector: ".design-origin" })).toBeInTheDocument();
    expect(screen.getByText(/Behavior design_1\/B1/)).toBeInTheDocument();
    expect(screen.getByText(/Practice design_1\/P1/)).toBeInTheDocument();
    fireEvent.click(within(trace).getByText("View trace, evidence & provenance"));
    expect(trace).toHaveAttribute("open");
    expect(within(trace).getByText(/independent alignment review \(M6\)/)).toBeInTheDocument();
  });

  it.each(["non_training", "investigate"] as const)("presents %s as an intentional result without training artifacts", (kind) => {
    const result = designFixture(kind);
    expect(isDesignResult(result)).toBe(true);
    render(<DesignWorkspace result={result} />);
    for (const heading of ["Learning plan", "Target behavior", "Hands-on practice", "Practice rubric", "READY FOR ALIGNMENT REVIEW"])
      expect(screen.queryByText(heading)).not.toBeInTheDocument();
    expect(screen.getByText(kind === "investigate" ? "MORE EVIDENCE NEEDED" : "TRAINING NOT SELECTED")).toBeInTheDocument();
    expect(screen.getByText("Review next step")).toBeInTheDocument();
    expect(screen.getByText("Limited sample")).toBeInTheDocument();
    expect(screen.getByText(/Design origin: Controlled non-AI fixture/, { selector: ".design-origin" })).toBeInTheDocument();
    expect(screen.getByText("View trace, evidence & provenance")).toBeInTheDocument();
    if (kind === "investigate") {
      expect(screen.getByText(/Current evidence is insufficient/)).toBeInTheDocument();
      expect(screen.getByText("Observe another call")).toBeInTheDocument();
    } else expect(screen.getByText(/No training outline, activities, practice, or rubric/)).toBeInTheDocument();
  });

  it("retains unresolved questions in the training path", () => {
    const result = designFixture();
    result.intervention.unresolved_questions = ["Is the script itself unclear?"];
    render(<DesignWorkspace result={result} />);
    expect(screen.getByText("Unresolved questions")).toBeInTheDocument();
    expect(screen.getByText("Is the script itself unclear?")).toBeInTheDocument();
  });

  it("renders exactly the provider supplied decision options and feedback as a design preview", () => {
    const result = designFixture();
    result.training_design!.decision_checks = [{ check_id: "design_1/K1", objective_ids: ["design_1/O1"], situation: "A member asks what happens next.", question: "Best response?",
      options: [
        { option_id: "design_1/K1_1", response: "Goodbye.", feedback: "Omits next step", correct: false },
        { option_id: "design_1/K1_2", response: "Here is the next step; what do you expect?", feedback: "Complete", correct: true },
        { option_id: "design_1/K1_3", response: "Call back.", feedback: "Vague", correct: false },
        { option_id: "design_1/K1_4", response: "The team handles it.", feedback: "Vague", correct: false }] }];
    expect(isDesignResult(result)).toBe(true);
    render(<DesignWorkspace result={result} />);
    const check = screen.getByRole("heading", { name: "Best response?" }).closest("article")!;
    expect(within(check).getAllByRole("listitem")).toHaveLength(4);
    for (const option of result.training_design!.decision_checks[0].options)
      expect(within(check).getByText(option.response)).toBeInTheDocument();
    expect(within(check).getByText("Feedback: Complete")).toBeInTheDocument();
    expect(screen.getAllByText("(intended correct response)")).toHaveLength(1);
    expect(screen.getByText(/Design preview · not a learner assessment/)).toBeInTheDocument();
    for (const claim of [/validated training/i, /approved training/i, /aligned training/i])
      expect(screen.queryByText(claim)).not.toBeInTheDocument();
  });

  it("retains scenario guidance in an accessible disclosure", () => {
    render(<DesignWorkspace result={designFixture()} />);
    const details = screen.getByText("View scenario guidance and conversation beats").closest("details")!;
    fireEvent.click(within(details).getByText("View scenario guidance and conversation beats"));
    expect(details).toHaveAttribute("open");
    for (const text of ["Request exists", "Next step", "Prior confusion", "Confirms", "Repeats question", "What was clear?"])
      expect(within(details).getByText(text)).toBeInTheDocument();
  });

  it("refuses malformed result shapes", () => {
    const base = designFixture();
    expect(isDesignResult({ ...base, training_design: { target_behaviors: null } })).toBe(false);
    expect(isDesignResult({ ...base, intervention: { ...base.intervention, decision_type: "guess" } })).toBe(false);
    expect(isDesignResult({ ...base, status: "aligned" })).toBe(false);
    expect(isDesignResult({ ...base, intervention: { ...base.intervention, provider_metadata: undefined } })).toBe(false);
    expect(isDesignResult({ ...base, intervention: { ...base.intervention, next_actions: [] } })).toBe(false);
    expect(isDesignResult({ ...base, training_design: { ...base.training_design!, practice_scenarios: [{ ...base.training_design!.practice_scenarios[0], rubric: [] }] } })).toBe(false);
    expect(isDesignResult({ ...base, training_design: { ...base.training_design!, practice_scenarios: [{ ...base.training_design!.practice_scenarios[0], persona: null }] } })).toBe(false);
    const twoCorrect = designFixture();
    twoCorrect.training_design!.decision_checks = [{ check_id: "design_1/K1", objective_ids: ["design_1/O1"], situation: "s", question: "q",
      options: [1, 2, 3, 4].map((n) => ({ option_id: `design_1/K1_${n}`, response: "r", feedback: "f", correct: n < 3 })) }];
    expect(isDesignResult(twoCorrect)).toBe(false);
    const investigateWithoutQuestions = designFixture("investigate");
    investigateWithoutQuestions.intervention.unresolved_questions = [];
    expect(isDesignResult(investigateWithoutQuestions)).toBe(false);
    const nonTrainingWithPlan = { ...designFixture("non_training"), training_design: base.training_design };
    expect(isDesignResult(nonTrainingWithPlan)).toBe(false);
    expect(isDesignResult(null)).toBe(false);
    expect(isDesignResult("truncated")).toBe(false);
  });
});
