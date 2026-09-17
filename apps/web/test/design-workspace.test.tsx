import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DesignWorkspace from "../app/design-workspace";
import { isDesignResult } from "../lib/designs";
import { designFixture } from "./design-workspace.test-fixture";

describe("M5 result rendering", () => {
  it("shows the training chain and proposed status", () => {
    const result = designFixture();
    expect(isDesignResult(result)).toBe(true);
    render(<DesignWorkspace result={result} />);
    expect(screen.getByText("CONTROLLED NON-AI DEMO PROPOSAL")).toBeInTheDocument();
    expect(screen.getByText("READY FOR ALIGNMENT REVIEW")).toBeInTheDocument();
    expect(screen.getByText("Target behaviors")).toBeInTheDocument();
    expect(screen.getByText("Objectives")).toBeInTheDocument();
    expect(screen.getByText("Training outline")).toBeInTheDocument();
    expect(screen.getByText("Proposed activities")).toBeInTheDocument();
    expect(screen.getByText("Hands-on practice")).toBeInTheDocument();
    expect(screen.getByText("Practice rubric")).toBeInTheDocument();
    expect(screen.getByText(/Target behavior.*Objective.*Validated diagnosis/)).toBeInTheDocument();
  });
  it.each(["non_training", "investigate"] as const)("shows %s without training artifacts", (kind) => {
    const result = designFixture(kind);
    expect(isDesignResult(result)).toBe(true);
    render(<DesignWorkspace result={result} />);
    for (const heading of ["Training outline", "Target behaviors", "Hands-on practice", "Practice rubric", "READY FOR ALIGNMENT REVIEW"])
      expect(screen.queryByText(heading)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(`Proposed intervention: ${kind === "investigate" ? "Investigate" : "Non Training"}`);
    expect(screen.getByText("Proposed next actions")).toBeInTheDocument();
    expect(screen.getByText("Review next step")).toBeInTheDocument();
    expect(screen.getByText("Limited sample")).toBeInTheDocument();
    expect(screen.getByText(/Controlled non-AI fixture \(test-fixture\)/)).toBeInTheDocument();
    if (kind === "investigate") {
      expect(screen.getByText("Additional evidence required")).toBeInTheDocument();
      expect(screen.getByText(/No training has been designed/)).toBeInTheDocument();
      expect(screen.getByText("Observe another call")).toBeInTheDocument();
    } else {
      expect(screen.getByText("Training not selected")).toBeInTheDocument();
      expect(screen.getByText(/No training outline, activities, practice, or rubric were generated/)).toBeInTheDocument();
    }
  });
  it("shows unresolved questions on a training proposal instead of hiding them", () => {
    const result = designFixture();
    result.intervention.unresolved_questions = ["Is the script itself unclear?"];
    render(<DesignWorkspace result={result} />);
    expect(screen.getByText("Unresolved questions")).toBeInTheDocument();
    expect(screen.getByText("Is the script itself unclear?")).toBeInTheDocument();
  });
  it("marks the intended correct decision-check response and labels the fixture origin", () => {
    const result = designFixture();
    result.training_design!.decision_checks = [{ check_id: "design_1/K1", objective_ids: ["design_1/O1"], situation: "A member asks what happens next.", question: "Best response?",
      options: [
        { option_id: "design_1/K1_1", response: "Goodbye.", feedback: "Omits next step", correct: false },
        { option_id: "design_1/K1_2", response: "Here is the next step; what do you expect?", feedback: "Complete", correct: true },
        { option_id: "design_1/K1_3", response: "Call back.", feedback: "Vague", correct: false },
        { option_id: "design_1/K1_4", response: "The team handles it.", feedback: "Vague", correct: false }] }];
    expect(isDesignResult(result)).toBe(true);
    render(<DesignWorkspace result={result} />);
    expect(screen.getAllByText("(intended correct response)")).toHaveLength(1);
    expect(screen.getByText(/Design origin: Controlled non-AI fixture \(test-fixture\)/)).toBeInTheDocument();
    expect(screen.getByText(/independent alignment review \(M6\)/)).toBeInTheDocument();
    for (const claim of [/validated training/i, /approved training/i, /aligned training/i])
      expect(screen.queryByText(claim)).not.toBeInTheDocument();
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
