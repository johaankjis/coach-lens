import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DesignWorkspace from "../app/design-workspace";
import { isDesignResult, type DesignResult } from "../lib/designs";
import { designFixture } from "./design-workspace.test-fixture";

// A provider-backed AWS-5 package: the M5 fixture plus the optional design basis, missing
// operational details, scripted-turn fields, and the service-built alignment trace.
function providerPackage(): DesignResult {
  const base = designFixture();
  const d = base.training_design!;
  const run = base.run_id;
  return {
    ...base,
    generation_mode: "provider",
    training_design: {
      ...d,
      objectives: [{ ...d.objectives[0], condition: "During a simulated call", observable_action: "summarize and confirm", standard: "both elements audible before the close" }],
      practice_scenarios: [{
        ...d.practice_scenarios[0],
        scenario_setup: "Facilitator plays the member with the request status visible.",
        escalation_expectation: null,
        beats: [{ ...d.practice_scenarios[0].beats[0], expected_learner_behavior: "Name the specific next action.", facilitator_cue: "Listen for a confirming question.", behavior_ids: [`${run}/B1`] },
                { beat_id: `${run}/BEAT2`, trigger: "Learner names the action", likely_response: "When?", success_branch: "Agrees", challenge_branch: "Asks again", expected_learner_behavior: "State timing as [PLACEHOLDER:M1].", facilitator_cue: "Watch for invented timing.", behavior_ids: [`${run}/B1`] }],
      }],
      design_basis: {
        gap: { diagnosis_id: "hyp_1", signal_id: "sig_1", observed_behavior: "Missed clarity", cause_domain: "skill_gap", performance_dimension: "capability", human_revised: false },
        intervention: { run_id: run, decision_type: "training", intervention_type: "practice_simulation", intervention_id: "int_abc", solution_validation_id: "sol_def", solution_alignment: "aligned", training_design_gate: "permitted", training_focus: "skill", validation_source: "aws4_solution_validator", summary: "Practice the resolution summary.", target_change: "State the resolution and confirm the next step." },
        guidance_version: "resultscx-design-guidance/1",
        supplied_operational_context: [],
      },
      missing_operational_details: [{ detail_id: `${run}/M1`, placeholder: "[PLACEHOLDER:M1]", description: "Expected follow-up timing was not supplied.", needed_for: "Practice turn BEAT2" }],
      provider_metadata: { provider: "Amazon Bedrock", model: "global.anthropic.claude-sonnet-4-6" },
    },
    alignment_trace: {
      run_id: run, diagnosis_id: "hyp_1", assessment: "structural_references_only",
      links: [{ diagnosis_id: "hyp_1", intervention_run_id: run, behavior_id: `${run}/B1`, objective_id: `${run}/O1`, activity_id: `${run}/A1`, scenario_id: `${run}/P1`, criterion_id: `${run}/R1` }],
      knowledge_check_links: [], missing_operational_detail_ids: [`${run}/M1`],
    },
  };
}

describe("AWS-5 provider-backed training package", () => {
  it("still satisfies the result guard with the optional fields present or absent", () => {
    expect(isDesignResult(providerPackage())).toBe(true);
    expect(isDesignResult(designFixture())).toBe(true);
    const broken = providerPackage();
    broken.training_design!.design_basis = { ...broken.training_design!.design_basis!, guidance_version: "" };
    expect(isDesignResult(broken)).toBe(false);
    // A basis that does not name a permitted, aligned AWS-4 handoff is not a provider package.
    for (const forged of [{ training_design_gate: "withheld" }, { solution_alignment: "partially_aligned" }, { validation_source: "m5_intervention_decision" }, { intervention_type: "coaching" }, { intervention_id: "" }]) {
      const withForgedBasis = providerPackage();
      withForgedBasis.training_design!.design_basis = { ...withForgedBasis.training_design!.design_basis!, intervention: { ...withForgedBasis.training_design!.design_basis!.intervention, ...(forged as object) } };
      expect(isDesignResult(withForgedBasis)).toBe(false);
    }
  });

  it("shows the design basis, missing details, and scripted practice turns", () => {
    render(<DesignWorkspace result={providerPackage()} />);
    expect(screen.getByText("AI-GENERATED INTERVENTION PROPOSAL")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What this package was designed from" })).toBeInTheDocument();
    expect(screen.getByText(/Skill focus/)).toHaveTextContent("Practice Simulation · solution-validated by the AWS-4 review (int_abc → sol_def)");
    expect(screen.getByText("State the resolution and confirm the next step.")).toBeInTheDocument();
    expect(screen.getByText("resultscx-design-guidance/1")).toBeInTheDocument();
    expect(screen.getByText(/None\. Any operational detail/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Placeholders the designer did not fill in" })).toBeInTheDocument();
    expect(screen.getByText("[PLACEHOLDER:M1]")).toBeInTheDocument();
    expect(screen.getByText("Standard: both elements audible before the close")).toBeInTheDocument();
    expect(screen.getByText("Facilitator plays the member with the request status visible.")).toBeInTheDocument();
    expect(screen.getByText("No escalation procedure was supplied, so none is scripted.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View scenario guidance and conversation beats"));
    expect(screen.getByText("Expected learner behavior: Name the specific next action.")).toBeInTheDocument();
    expect(screen.getByText("Facilitator cue: Listen for a confirming question.")).toBeInTheDocument();
    expect(screen.getByText("No learner has been scored.")).toBeInTheDocument();
  });

  it("renders the fixture without the AWS-5 sections", () => {
    render(<DesignWorkspace result={designFixture()} />);
    expect(screen.queryByText("What this package was designed from")).not.toBeInTheDocument();
    expect(screen.queryByText("Placeholders the designer did not fill in")).not.toBeInTheDocument();
    expect(screen.queryByText(/Escalation handling/)).not.toBeInTheDocument();
  });
});
