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
    expect(screen.queryByText("Training outline")).not.toBeInTheDocument();
    expect(screen.queryByText("READY FOR ALIGNMENT REVIEW")).not.toBeInTheDocument();
    expect(screen.getByText("Recommended next actions")).toBeInTheDocument();
    if (kind === "investigate") expect(screen.getByText("Additional evidence required")).toBeInTheDocument();
  });
  it("refuses malformed result shapes", () => {
    expect(isDesignResult({ ...designFixture(), training_design: { target_behaviors: null } })).toBe(false);
    expect(isDesignResult({ ...designFixture(), intervention: { ...designFixture().intervention, decision_type: "guess" } })).toBe(false);
  });
});
