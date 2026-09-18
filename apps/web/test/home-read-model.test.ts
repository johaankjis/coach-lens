import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadHomeSources } from "../lib/home/load";
import { buildHomeReadModel, isRuntimeMode, type PipelineStep } from "../lib/home/read-model";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";
import {
  alignmentReviewFixture,
  approved,
  awaiting,
  cleanSignal,
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

const steps = (pipeline: PipelineStep[]) => Object.fromEntries(pipeline.map((step) => [step.id, `${step.tone}:${step.text}`]));
const stage = (model: ReturnType<typeof buildHomeReadModel>, id: string) => model.downstream.find((item) => item.id === id)!;

describe("Home read-model builder", () => {
  it("maps backend counts without recomputing them and keeps the backend ranking", () => {
    const model = buildHomeReadModel(sources());
    expect(model.observedSignalCount).toBe(3);
    expect(model.gaps.map((gap) => gap.signalId)).toEqual(["sig_top", "sig_second", "sig_clean"]);
    expect(model.gaps[0]).toMatchObject({
      rank: 1,
      criterion: "Resolution clarity",
      failCount: 7,
      evaluatedResults: 12,
      failRateLabel: "58.3%",
      coverage: { evaluated: 12, total: 20 },
      href: "/agent-insights?signal=sig_top",
    });
    expect(model.gaps[0].failRateFraction).toBeCloseTo(0.5833);
    const priority = model.summary.find((metric) => metric.id === "priority")!;
    expect(priority.reading).toMatchObject({ state: "pending", reason: expect.stringContaining("not classified") });
  });

  it("caps the gap list at five while reporting the full observed count", () => {
    const many = Array.from({ length: 8 }, (_, index) => ({ ...cleanSignal, signal_id: `sig_${index}` }));
    const model = buildHomeReadModel(sources({ signals: many, priority: null }));
    expect(model.gaps).toHaveLength(5);
    expect(model.observedSignalCount).toBe(8);
  });

  it("keeps agents monitored, priority issues, overall QA, and the intervention tile pending rather than inventing values", () => {
    const model = buildHomeReadModel(sources());
    const byId = Object.fromEntries(model.summary.map((metric) => [metric.id, metric.reading]));
    expect(byId.agents).toMatchObject({ state: "pending", note: "20 QA evaluations loaded" });
    expect(byId.priority).toMatchObject({ state: "pending" });
    expect(byId.qa).toMatchObject({ state: "pending", note: "3 criteria observed" });
    expect(byId.intervention).toMatchObject({ state: "pending", note: "Selected insight: awaiting human validation" });
    expect(model.downstream.map((item) => [item.id, item.status])).toEqual([
      ["intervention", "blocked"],
      ["training", "blocked"],
      ["alignment", "blocked"],
      ["outcome", "pending_backend"],
    ]);
  });

  it("represents an empty backend explicitly (B: no QA)", () => {
    const model = buildHomeReadModel(sources({ signals: [], priority: null, mode: { ...realMode, evaluation_count: 0, signal_count: 0 } }));
    expect(model.priority).toBeNull();
    expect(model.gaps).toEqual([]);
    expect(model.summary.find((metric) => metric.id === "priority")!.reading).toMatchObject({ state: "pending", note: "0 observed criteria loaded" });
    expect(model.summary.every((metric) => metric.reading.state === "pending")).toBe(true);
    expect(stage(model, "outcome").status).toBe("pending_backend");
  });

  it("separates fixture, real, and unknown provenance and echoes the AWS-4 providers", () => {
    expect(buildHomeReadModel(sources({ mode: demoMode })).provenance).toMatchObject({ kind: "synthetic_demo", label: "Synthetic demo", interventionProvider: "controlled_fixture", solutionValidator: "controlled_fixture" });
    expect(buildHomeReadModel(sources({ mode: realMode })).provenance).toMatchObject({ kind: "real_results_cx", label: "Real ResultsCX · local" });
    expect(buildHomeReadModel(sources({ mode: null })).provenance).toMatchObject({ kind: "unknown", evaluationCount: null, interventionProvider: "unknown" });
    expect(buildHomeReadModel(sources({ mode: { ...realMode, mode: "something_new" } })).provenance.kind).toBe("unknown");
  });

  it("builds the selected insight from the top signal and the latest record (D: awaiting review)", () => {
    const model = buildHomeReadModel(sources());
    const selected = model.priority!;
    expect(selected).toMatchObject({
      signalId: "sig_top",
      criterion: "Resolution clarity",
      domain: "Member Experience",
      failure: { failCount: 7, evaluatedResults: 12, failRateLabel: "58.3%", feedbackCount: 9, coverage: { evaluated: 12, total: 20 } },
      humanValidation: { state: "awaiting_review" },
      evidenceReview: { state: "not_run" },
      intervention: { state: "blocked" },
      training: { state: "blocked" },
      alignment: { state: "blocked" },
      outcome: { state: "pending" },
      reviewHref: "/agent-insights?signal=sig_top",
      nextStep: { label: "Review diagnosis", href: "/agent-insights?signal=sig_top" },
    });
    expect(selected.diagnosis).toMatchObject({ state: "proposed", origin: "ai", causeDomain: "Skill Gap", performanceDimension: "Capability", confidence: { value: "0.78" } });
    expect((selected.diagnosis as { confidence: { wording: string } }).confidence.wording).toMatch(/not a statistically calibrated probability/);
    expect(selected.evidence).toMatchObject({ supporting: awaiting.provider_hypothesis.supporting_evidence, missing: ["Observe a live call"] });
    expect(steps(selected.pipeline)).toEqual({
      observed: "validated:Deterministic",
      diagnosed: "proposed:Proposed",
      evidence_reviewed: "neutral:Not run",
      human_validated: "pending:Awaiting review",
      intervention_proposed: "neutral:Blocked",
      solution_validated: "neutral:Blocked",
      training_generated: "neutral:Blocked",
      alignment: "neutral:Blocked",
    });
  });

  it("recognizes a controlled fixture record as non-AI", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: fixtureRecord, validation: validatedReview }) }));
    expect(model.priority!.diagnosis).toMatchObject({ state: "proposed", origin: "fixture" });
    expect(model.priority!.evidenceReview).toMatchObject({ state: "evidence_validated" });
  });

  it("reports an observed signal with no diagnosis (C) and routes to evidence review", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: null }) }));
    expect(model.priority!.diagnosis).toEqual({ state: "not_requested" });
    expect(model.priority!.evidenceReview).toEqual({ state: "not_applicable" });
    expect(model.priority!.humanValidation.state).toBe("none");
    expect(model.priority!.evidence).toBeNull();
    expect(model.priority!.nextStep).toMatchObject({ label: "Review observed evidence and run diagnosis", href: "/agent-insights?signal=sig_top" });
    expect(steps(model.priority!.pipeline).diagnosed).toBe("neutral:Not requested");
  });

  it("does not recommend diagnosis from an all-pass criterion", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ signal: cleanSignal, record: null }) }));
    expect(model.priority!.nextStep).toMatchObject({ label: "Inspect observed criterion", detail: expect.stringContaining("No failed results") });
  });

  it("maps validated and questioned semantic reviews (E) and ignores a review for another hypothesis", () => {
    const validated = buildHomeReadModel(sources({ priority: insight({ validation: validatedReview }) }));
    expect(validated.priority!.evidenceReview).toMatchObject({ state: "evidence_validated", outcome: "Supported", unsupportedClaims: 0 });
    expect(steps(validated.priority!.pipeline).evidence_reviewed).toBe("validated:Validated");
    const questioned = buildHomeReadModel(sources({ priority: insight({ validation: questionedReview }) }));
    expect(questioned.priority!.evidenceReview).toMatchObject({ state: "evidence_questioned", outcome: "Unsupported", unsupportedClaims: 1, missingEvidence: 1 });
    // Evidence questioned is a semantic caution; the human decision is still open.
    expect(questioned.priority!.humanValidation.state).toBe("awaiting_review");
    expect(steps(questioned.priority!.pipeline).evidence_reviewed).toBe("caution:Questioned");
    expect(steps(questioned.priority!.pipeline).human_validated).toBe("pending:Awaiting review");
    expect(questioned.priority!.nextStep.label).toBe("Review diagnosis");
    const foreign = buildHomeReadModel(sources({ priority: insight({ validation: { ...validatedReview, hypothesis_id: "hyp_other" } }) }));
    expect(foreign.priority!.evidenceReview).toEqual({ state: "not_run" });
  });

  it("maps every human validation state with the recorded reviewer (F: approved)", () => {
    const state = (record: typeof awaiting) => buildHomeReadModel(sources({ priority: insight({ record }) })).priority!;
    expect(state(approved).humanValidation).toEqual({ state: "approved", reviewer: "qa-lead", rationale: null });
    // Human approval of the diagnosis is not an intervention decision and not solution validation.
    expect(state(approved).intervention).toEqual({ state: "not_started" });
    expect(state(approved).training).toMatchObject({ state: "blocked" });
    expect(state(approved).nextStep).toMatchObject({ label: "Generate intervention", href: "/agent-insights?signal=sig_top" });
    expect(steps(state(approved).pipeline)).toMatchObject({ human_validated: "validated:Approved", intervention_proposed: "pending:Not proposed", solution_validated: "neutral:Blocked" });
    expect(state(revisedPending).humanValidation).toMatchObject({ state: "revised_pending", reviewer: "qa-2" });
    expect(state(revisedPending).nextStep.label).toBe("Approve human revision");
    expect(state(revisedPending).diagnosis).toMatchObject({ humanRevised: true, causeDomain: "Process Gap" });
    expect(state(revisedApproved).humanValidation).toMatchObject({ state: "revised_approved", reviewer: "qa-lead" });
    expect(state(revisedApproved).intervention).toEqual({ state: "not_started" });
    expect(state(rejected).humanValidation).toEqual({ state: "rejected", reviewer: "qa-3", rationale: "Evidence too thin" });
    expect(state(rejected).nextStep.label).toBe("Request another hypothesis");
    expect(steps(state(rejected).pipeline).human_validated).toBe("rejected:Rejected");
  });

  it("shows an AWS-4 proposal as proposed with solution validation pending (G)", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", null) }) }));
    const selected = model.priority!;
    expect(selected.intervention).toMatchObject({
      state: "proposed",
      typeLabel: "Training",
      decisionType: "training",
      recommendation: "Rehearse the closing summary in short simulated calls.",
      targetChange: "State the next step and confirm member understanding before closing.",
      solution: null,
      trainingDesignGate: "awaiting_solution_validation",
      origin: "ai",
    });
    expect(selected.training).toMatchObject({ state: "awaiting_solution" });
    expect(selected.nextStep).toMatchObject({ label: "Validate solution", href: "/agent-insights?signal=sig_top" });
    expect(steps(selected.pipeline)).toMatchObject({ intervention_proposed: "proposed:Training", solution_validated: "pending:Awaiting validation", training_generated: "neutral:Awaiting solution" });
    expect(stage(model, "intervention")).toMatchObject({ status: "proposed", hrefLabel: "Validate solution" });
    expect(model.summary.find((metric) => metric.id === "intervention")!.reading).toMatchObject({ note: "Selected insight: training proposed" });
  });

  it("shows an aligned training intervention as permitted but not generated (H)", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned") }) }));
    const selected = model.priority!;
    expect(selected.intervention).toMatchObject({ state: "solution_validated", typeLabel: "Practice Simulation", trainingDesignGate: "permitted", solution: { status: "solution_validated", alignment: "Aligned", assessment: "Practice addresses the validated skill gap." } });
    expect(selected.training).toMatchObject({ state: "permitted" });
    expect(selected.alignment).toMatchObject({ state: "blocked" });
    expect(selected.nextStep).toMatchObject({ label: "Generate training", href: "/agent-insights?signal=sig_top" });
    expect(steps(selected.pipeline)).toMatchObject({ solution_validated: "validated:Validated", training_generated: "pending:Not generated", alignment: "neutral:Blocked" });
    expect(stage(model, "intervention")).toMatchObject({ status: "validated", detail: expect.stringContaining("Not a human approval") });
    expect(stage(model, "training")).toMatchObject({ status: "not_started", hrefLabel: "Generate training" });
  });

  it("withholds training when the solution is questioned (I)", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "misaligned") }) }));
    const selected = model.priority!;
    expect(selected.intervention).toMatchObject({ state: "solution_questioned", trainingDesignGate: "withheld", solution: { status: "solution_questioned", alignment: "Misaligned", misalignedPoints: 1 } });
    expect(selected.training).toMatchObject({ state: "withheld", reason: expect.stringContaining("withheld") });
    expect(selected.nextStep).toMatchObject({ label: "Review solution concerns", href: "/agent-insights?signal=sig_top" });
    expect(steps(selected.pipeline)).toMatchObject({ solution_validated: "caution:Questioned", training_generated: "caution:Withheld", alignment: "neutral:Blocked" });
    // A questioned solution is a caution, never a human rejection.
    expect(selected.pipeline.some((step) => step.tone === "rejected")).toBe(false);
    expect(stage(model, "intervention")).toMatchObject({ status: "questioned", hrefLabel: "Review solution concerns" });
    expect(stage(model, "training").status).toBe("withheld");
  });

  it("marks training not applicable, not failed, for a validated process correction (J)", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("process_correction", "aligned"), design: designFixture("non_training") }) }));
    const selected = model.priority!;
    expect(selected.intervention).toMatchObject({ state: "solution_validated", typeLabel: "Process Correction", decisionType: "non_training", trainingDesignGate: "not_applicable" });
    expect(selected.training).toMatchObject({ state: "not_applicable", reason: expect.stringContaining("does not call for training") });
    expect(selected.alignment).toMatchObject({ state: "not_applicable" });
    expect(selected.nextStep).toMatchObject({ label: "Review validated process intervention", href: "/agent-insights?signal=sig_top" });
    expect(steps(selected.pipeline)).toMatchObject({ solution_validated: "validated:Validated", training_generated: "not_applicable:Not applicable", alignment: "not_applicable:Not applicable" });
    expect(selected.pipeline.some((step) => step.tone === "caution" || step.tone === "rejected")).toBe(false);
    expect(stage(model, "training").status).toBe("not_applicable");
    // A questioned process correction is also not a training failure.
    const questioned = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("coaching", "partially_aligned") }) })).priority!;
    expect(questioned.training).toMatchObject({ state: "not_applicable", reason: expect.stringContaining("questioned") });
    expect(questioned.nextStep.label).toBe("Review solution concerns");
    const investigate = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("investigate_further", "aligned") }) })).priority!;
    expect(investigate.nextStep.label).toBe("Review investigation recommendation");
  });

  it("shows a generated AWS-5 package with alignment pending and outcome pending (K, N)", () => {
    const model = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage() }) }));
    const selected = model.priority!;
    expect(selected.training).toMatchObject({
      state: "generated",
      designStatus: "ready_for_alignment_review",
      readyForAlignmentReview: true,
      origin: "ai",
      targetBehaviors: ["State next step and check understanding"],
      objectiveCount: 1,
      outlineSectionCount: 1,
      activityCount: 1,
      knowledgeCheckCount: 1,
      practiceScenarioCount: 1,
      missingOperationalDetailCount: 1,
      plannedMinutes: 12,
      trainingHref: "/training?signal=sig_top",
      rolePlayHref: "/role-play?signal=sig_top",
    });
    expect(selected.alignment).toMatchObject({ state: "pending", reason: expect.stringContaining("Not yet reviewed") });
    expect(selected.outcome).toMatchObject({ state: "pending", reason: expect.stringContaining("Outcome measurement pending") });
    // Test 1: generated training with no AWS-6 record → alignment pending, next action routes to Check Alignment.
    expect(selected.nextStep).toMatchObject({ label: "Review training alignment", href: "/agent-insights?signal=sig_top", detail: expect.stringContaining("not deployed") });
    expect(steps(selected.pipeline)).toMatchObject({ training_generated: "validated:Generated", alignment: "pending:Pending" });
    expect(stage(model, "training")).toMatchObject({ status: "generated", hrefLabel: "Open training package", href: "/training?signal=sig_top", detail: expect.stringContaining("not deployed") });
    expect(stage(model, "alignment")).toMatchObject({ status: "pending", hrefLabel: "Review training alignment", href: "/agent-insights?signal=sig_top" });
    expect(stage(model, "outcome")).toMatchObject({ status: "pending_backend", href: "/kpi-tracker" });
    expect(model.summary.find((metric) => metric.id === "intervention")!.reading).toMatchObject({ state: "pending", note: "Selected insight: training package generated, alignment pending" });
    const fixture = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "aligned", { fixture: true }), design: designFixture("training") }) })).priority!;
    expect(fixture.training).toMatchObject({ state: "generated", origin: "fixture", knowledgeCheckCount: 0, missingOperationalDetailCount: 0 });
    expect(fixture.intervention).toMatchObject({ origin: "fixture" });
  });

  it("ignores AWS-4 and AWS-5 records that belong to another diagnosis or an unvalidated record", () => {
    const foreign = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: { ...interventionFixture("training", "aligned"), hypothesis_id: "hyp_other" }, design: { ...designFixture("training"), diagnosis_id: "hyp_other" } }) })).priority!;
    expect(foreign.intervention).toEqual({ state: "not_started" });
    expect(foreign.training.state).toBe("blocked");
    const unvalidated = buildHomeReadModel(sources({ priority: insight({ record: awaiting, intervention: interventionFixture("training", "aligned"), design: designFixture("training") }) })).priority!;
    expect(unvalidated.intervention).toEqual({ state: "blocked" });
    expect(unvalidated.training.state).toBe("blocked");
  });

  it("does not attach stale signal, intervention, or package records to the selected insight", () => {
    const intervention = interventionFixture("practice_simulation", "aligned");
    const packageResult = providerPackage();
    const selected = (overrides: Partial<ReturnType<typeof insight>>) =>
      buildHomeReadModel(sources({ priority: insight({ record: approved, intervention, design: packageResult, ...overrides }) })).priority!;

    expect(selected({ record: { ...approved, provider_hypothesis: { ...approved.provider_hypothesis, signal_id: "sig_second" } } }).diagnosis.state).toBe("not_requested");
    expect(selected({ intervention: { ...intervention, signal_id: "sig_second" } }).training.state).toBe("blocked");
    expect(selected({ design: { ...packageResult, approved_diagnosis: { ...packageResult.approved_diagnosis, signal_id: "sig_second" } } }).training.state).toBe("permitted");
    expect(selected({ design: { ...packageResult, intervention: { ...packageResult.intervention, intervention_id: "old_intervention" } } }).training.state).toBe("permitted");
    expect(selected({ design: { ...packageResult, intervention: { ...packageResult.intervention, solution_validation_id: "old_validation" } } }).training.state).toBe("permitted");
  });

  describe("AWS-6 alignment review", () => {
    const reviewed = (outcome: Parameters<typeof alignmentReviewFixture>[0], overrides: Partial<ReturnType<typeof insight>> = {}) =>
      buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage(), alignment: alignmentReviewFixture(outcome), ...overrides }) }));

    it("maps an aligned review to Design aligned with the review summary and routes to the aligned package (test 2)", () => {
      const model = reviewed("aligned");
      const selected = model.priority!;
      expect(selected.alignment).toMatchObject({
        state: "design_aligned",
        reviewId: "alr_aligned",
        runId: "design_1",
        outcome: "aligned",
        outcomeLabel: "Aligned",
        assessment: "The package trains the confirmed closing behavior.",
        confidence: { value: "0.8", wording: expect.stringContaining("not a statistically calibrated probability") },
        origin: "ai",
        problematicElements: [],
        unsupportedAssumptions: [],
        missingInformation: [],
      });
      expect(selected.training.state).toBe("generated");
      expect(steps(selected.pipeline)).toMatchObject({ solution_validated: "validated:Validated", training_generated: "validated:Generated", alignment: "validated:Design aligned" });
      expect(selected.nextStep).toMatchObject({ label: "Review aligned training package", href: "/training?signal=sig_top", detail: expect.stringContaining("not deployed") });
      expect(selected.nextStep.detail).not.toMatch(/deploy(ed|ment) (is|has)|improve/i);
      expect(stage(model, "alignment")).toMatchObject({ status: "design_aligned", hrefLabel: "Review aligned training package", href: "/training?signal=sig_top", detail: expect.stringContaining("not a human decision") });
      expect(stage(model, "outcome")).toMatchObject({ status: "pending_backend", detail: expect.stringContaining("Outcome measurement pending") });
      expect(model.summary.find((metric) => metric.id === "intervention")!.reading).toMatchObject({ note: "Selected insight: training package generated, design aligned" });
    });

    it.each([
      ["partially_aligned", "Partially Aligned"],
      ["misaligned", "Misaligned"],
      ["insufficient_information", "Insufficient Information"],
    ] as const)("maps a %s review to Design questioned and routes to the alignment concerns (tests 3-5)", (outcome, outcomeLabel) => {
      const model = reviewed(outcome);
      const selected = model.priority!;
      expect(selected.alignment).toMatchObject({ state: "design_questioned", outcome, outcomeLabel, problematicElements: ["A1"], unsupportedAssumptions: ["Assumes a follow-up message is sent automatically."] });
      expect(steps(selected.pipeline)).toMatchObject({ training_generated: "validated:Generated", alignment: "caution:Design questioned" });
      expect(selected.nextStep).toMatchObject({ label: "Review alignment concerns", href: "/agent-insights?signal=sig_top", detail: expect.stringContaining(outcomeLabel.toLowerCase()) });
      expect(stage(model, "alignment")).toMatchObject({ status: "design_questioned", hrefLabel: "Review alignment concerns", href: "/agent-insights?signal=sig_top" });
      // A questioned design never touches the upstream states or the outcome.
      expect(steps(selected.pipeline)).toMatchObject({ human_validated: "validated:Approved", solution_validated: "validated:Validated" });
      expect(selected.training.state).toBe("generated");
      expect(stage(model, "outcome").status).toBe("pending_backend");
      expect(model.summary.find((metric) => metric.id === "intervention")!.reading).toMatchObject({ note: "Selected insight: training package generated, design questioned" });
    });

    it("ignores a review for another design run, diagnosis, proposal, or solution validation (test 6)", () => {
      const pending = { state: "pending", reason: expect.stringContaining("Not yet reviewed") };
      expect(reviewed("aligned", { alignment: alignmentReviewFixture("aligned", { run_id: "design_0" }) }).priority!.alignment).toMatchObject(pending);
      expect(reviewed("misaligned", { alignment: alignmentReviewFixture("misaligned", { diagnosis_id: "hyp_other" }) }).priority!.alignment).toMatchObject(pending);
      expect(reviewed("aligned", { alignment: alignmentReviewFixture("aligned", { intervention_id: "int_old" }) }).priority!.alignment).toMatchObject(pending);
      expect(reviewed("aligned", { alignment: alignmentReviewFixture("aligned", { solution_validation_id: "sol_old" }) }).priority!.alignment).toMatchObject(pending);
      // A review can never make an unreviewed package look reviewed through the next step either.
      expect(reviewed("aligned", { alignment: alignmentReviewFixture("aligned", { run_id: "design_0" }) }).priority!.nextStep.label).toBe("Review training alignment");
    });

    it("keeps alignment not applicable for a validated process correction even if a review is stored (test 7)", () => {
      const model = reviewed("aligned", { intervention: interventionFixture("process_correction", "aligned"), design: designFixture("non_training") });
      const selected = model.priority!;
      expect(selected.training.state).toBe("not_applicable");
      expect(selected.alignment).toMatchObject({ state: "not_applicable" });
      expect(steps(selected.pipeline)).toMatchObject({ training_generated: "not_applicable:Not applicable", alignment: "not_applicable:Not applicable" });
      expect(selected.nextStep.label).toBe("Review validated process intervention");
    });

    it("keeps alignment blocked for a questioned solution even if a review is stored (test 8)", () => {
      const model = reviewed("aligned", { intervention: interventionFixture("practice_simulation", "misaligned") });
      const selected = model.priority!;
      expect(selected.training.state).toBe("withheld");
      expect(selected.alignment).toMatchObject({ state: "blocked" });
      expect(steps(selected.pipeline)).toMatchObject({ solution_validated: "caution:Questioned", training_generated: "caution:Withheld", alignment: "neutral:Blocked" });
      expect(selected.nextStep.label).toBe("Review solution concerns");
    });

    it("cannot show the previous signal's review when the selected signal changes (test 9)", () => {
      const model = reviewed("aligned", { signal: secondSignal });
      const selected = model.priority!;
      expect(selected.signalId).toBe("sig_second");
      expect(selected.diagnosis.state).toBe("not_requested");
      expect(selected.training.state).toBe("blocked");
      expect(selected.alignment).toMatchObject({ state: "blocked" });
      expect(steps(selected.pipeline)).toMatchObject({ alignment: "neutral:Blocked" });
    });

    it("never describes a reviewed design as deployed, effective, or an outcome (test 10)", () => {
      const text = JSON.stringify(reviewed("aligned"));
      expect(text).not.toMatch(/outcome validated|improv(ed|ement)|effective|has been deployed|deployed to/i);
      expect(text).toMatch(/Outcome measurement pending/);
    });
  });

  it("keeps current AWS-4 decision ahead of an outdated generated package", () => {
    const design = providerPackage();
    const questioned = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "misaligned"), design }) })).priority!;
    expect(questioned.training.state).toBe("withheld");
    expect(questioned.alignment.state).toBe("blocked");
    expect(questioned.nextStep.label).toBe("Review solution concerns");
    const process = buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("process_correction", "aligned"), design }) })).priority!;
    expect(process.training.state).toBe("not_applicable");
    expect(process.alignment.state).toBe("not_applicable");
  });

  it("validates the runtime mode shape with and without the AWS-4 provider fields", () => {
    expect(isRuntimeMode(realMode)).toBe(true);
    const older = { ...realMode };
    delete older.intervention_provider;
    delete older.solution_validator;
    expect(isRuntimeMode(older)).toBe(true);
    expect(isRuntimeMode({ ...realMode, intervention_provider: 3 })).toBe(false);
    expect(isRuntimeMode({ ...realMode, evaluation_count: "20" })).toBe(false);
    expect(isRuntimeMode(null)).toBe(false);
  });
});

function reply(value: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => value } as Response;
}

describe("Home source loader", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads mode, signals, the top signal's latest record, its semantic review, and the AWS-4 and AWS-5 records when validated", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      calls.push(path);
      if (path.endsWith("/mode")) return reply(demoMode);
      if (path.endsWith("/signals")) return reply([topSignal, secondSignal]);
      if (path.endsWith("/signals/sig_top/hypotheses")) return reply([approved, awaiting]);
      if (path.endsWith("/hypotheses/hyp_1/evidence-validation")) return reply(validatedReview);
      if (path.endsWith("/interventions/diagnoses/hyp_1")) return reply(interventionFixture("training", "aligned"));
      if (path.endsWith("/designs/diagnoses/hyp_1")) return reply(designFixture("training"));
      if (path.endsWith("/designs/diagnoses/hyp_1/alignment-review")) return reply({ detail: { code: "alignment_review_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    const result = await loadHomeSources();
    expect(result.mode).toEqual(demoMode);
    expect(result.signals).toHaveLength(2);
    expect(result.priority).toMatchObject({ signal: topSignal, record: approved, validation: validatedReview });
    expect(result.priority!.intervention!.proposal.intervention_id).toBe("int_1");
    expect(result.priority!.design!.run_id).toBe("design_1");
    expect(result.requested).toBeNull();
    expect(calls.some((path) => path.includes("sig_second"))).toBe(false);
  });

  it("loads the AWS-6 review for a generated package and drops one for another run (test 6)", async () => {
    const stub = (alignment: unknown, status = 200) => vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply([approved]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/interventions/")) return reply(interventionFixture("practice_simulation", "aligned"));
      if (path.endsWith("/alignment-review")) return reply(alignment, status);
      if (path.includes("/designs/")) return reply(providerPackage());
      throw new Error(`Unexpected route ${path}`);
    });
    vi.stubGlobal("fetch", stub(alignmentReviewFixture("aligned")));
    expect((await loadHomeSources()).priority!.alignment).toMatchObject({ alignment_review_id: "alr_aligned" });
    expect(vi.mocked(fetch).mock.calls.map(([path]) => path)).toContain("/api/designs/diagnoses/hyp_1/alignment-review");

    vi.stubGlobal("fetch", stub(alignmentReviewFixture("aligned", { run_id: "design_0" })));
    expect((await loadHomeSources()).priority!.alignment).toBeNull();

    // The backend refuses a review whose digest no longer matches the run: treat it as absent, not as an error.
    vi.stubGlobal("fetch", stub({ detail: { code: "alignment_review_stale" } }, 409));
    const stale = await loadHomeSources();
    expect(stale.priority!.alignment).toBeNull();
    expect(buildHomeReadModel(stale).priority!.alignment.state).toBe("pending");

    vi.stubGlobal("fetch", stub({ detail: { code: "alignment_review_not_found" } }, 404));
    expect((await loadHomeSources()).priority!.alignment).toBeNull();

    vi.stubGlobal("fetch", stub({ detail: { code: "boom" } }, 500));
    await expect(loadHomeSources()).rejects.toThrow();
  });

  it("does not request the AWS-6 review when no training package exists", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      calls.push(path);
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply([approved]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/interventions/")) return reply(interventionFixture("process_correction", "aligned"));
      if (path.includes("/designs/")) return reply(designFixture("non_training"));
      throw new Error(`Unexpected route ${path}`);
    }));
    expect((await loadHomeSources()).priority!.alignment).toBeNull();
    expect(calls.some((path) => path.endsWith("/alignment-review"))).toBe(false);
  });

  it("does not request AWS-4 or AWS-5 records for an unvalidated diagnosis", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      calls.push(path);
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply([awaiting]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    const result = await loadHomeSources();
    expect(result.priority).toMatchObject({ record: awaiting, intervention: null, design: null });
    expect(calls.some((path) => path.includes("/interventions/") || path.includes("/designs/"))).toBe(false);
  });

  it("treats 404 for the semantic review, intervention, and design as absent, and keeps other failures visible", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply([approved]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/interventions/")) return reply({ detail: { code: "intervention_not_found" } }, 404);
      if (path.endsWith("/alignment-review")) return reply({ detail: { code: "alignment_review_not_found" } }, 404);
      if (path.includes("/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    const result = await loadHomeSources();
    expect(result.priority).toMatchObject({ record: approved, validation: null, intervention: null, design: null });

    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply({ detail: { code: "boom" } }, 500);
      throw new Error(`Unexpected route ${path}`);
    }));
    await expect(loadHomeSources()).rejects.toThrow(/could not be completed/);
  });

  it("selects a requested signal and reports an unknown one while falling back (O)", async () => {
    const mock = vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal, secondSignal]);
      if (path.endsWith("/sig_second/hypotheses")) return reply([]);
      if (path.endsWith("/sig_top/hypotheses")) return reply([awaiting]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    });
    vi.stubGlobal("fetch", mock);
    const second = await loadHomeSources("sig_second");
    expect(second.priority).toMatchObject({ signal: secondSignal, record: null });
    expect(second.requested).toEqual({ signalId: "sig_second", found: true });
    const missing = await loadHomeSources("sig_missing");
    expect(missing.priority).toMatchObject({ signal: topSignal, record: awaiting });
    expect(missing.requested).toEqual({ signalId: "sig_missing", found: false });
    expect(mock).not.toHaveBeenCalledWith(expect.stringContaining("sig_missing"), expect.anything());
    expect(buildHomeReadModel(missing).requested).toEqual({ signalId: "sig_missing", found: false });
  });

  it("degrades provenance to unknown when the mode route fails but signals load", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply({ detail: { code: "not_found" } }, 404);
      if (path.endsWith("/signals")) return reply([]);
      throw new Error(`Unexpected route ${path}`);
    }));
    const result = await loadHomeSources();
    expect(result.mode).toBeNull();
    expect(result.priority).toBeNull();
    expect(buildHomeReadModel(result).provenance.kind).toBe("unknown");
  });

  it("fails when the diagnostic service is unreachable instead of showing an empty team (A)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    await expect(loadHomeSources()).rejects.toThrow(/diagnostic service is unavailable/);
  });
});
