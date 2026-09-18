import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadHomeSources } from "../lib/home/load";
import { buildHomeReadModel, isRuntimeMode } from "../lib/home/read-model";
import { designFixture } from "./design-workspace.test-fixture";
import {
  approved,
  awaiting,
  cleanSignal,
  demoMode,
  fixtureRecord,
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
    expect(priority.reading).toMatchObject({ state: "available", value: "2" });
  });

  it("caps the gap list at five while reporting the full observed count", () => {
    const many = Array.from({ length: 8 }, (_, index) => ({ ...cleanSignal, signal_id: `sig_${index}` }));
    const model = buildHomeReadModel(sources({ signals: many, priority: null }));
    expect(model.gaps).toHaveLength(5);
    expect(model.observedSignalCount).toBe(8);
  });

  it("marks agents monitored, overall QA, and intervention status as pending rather than inventing values", () => {
    const model = buildHomeReadModel(sources());
    const byId = Object.fromEntries(model.summary.map((metric) => [metric.id, metric.reading]));
    expect(byId.agents).toMatchObject({ state: "pending", note: "20 QA evaluations loaded" });
    expect(byId.qa).toMatchObject({ state: "pending", note: "3 criteria observed" });
    expect(byId.intervention).toMatchObject({ state: "pending" });
    expect(model.downstream.map((stage) => [stage.id, stage.status])).toEqual([
      ["intervention", "blocked"],
      ["training", "blocked"],
      ["alignment", "pending_backend"],
      ["outcome", "pending_backend"],
    ]);
  });

  it("represents an empty backend explicitly", () => {
    const model = buildHomeReadModel(sources({ signals: [], priority: null, mode: { ...realMode, evaluation_count: 0, signal_count: 0 } }));
    expect(model.priority).toBeNull();
    expect(model.gaps).toEqual([]);
    expect(model.summary.find((metric) => metric.id === "priority")!.reading).toMatchObject({ state: "unavailable" });
  });

  it("separates fixture, real, and unknown provenance", () => {
    expect(buildHomeReadModel(sources({ mode: demoMode })).provenance).toMatchObject({ kind: "synthetic_demo", label: "Synthetic demo" });
    expect(buildHomeReadModel(sources({ mode: realMode })).provenance).toMatchObject({ kind: "real_results_cx", label: "Real ResultsCX · local" });
    expect(buildHomeReadModel(sources({ mode: null })).provenance).toMatchObject({ kind: "unknown", evaluationCount: null });
    expect(buildHomeReadModel(sources({ mode: { ...realMode, mode: "something_new" } })).provenance.kind).toBe("unknown");
  });

  it("builds the priority insight from the top signal and the latest record", () => {
    const model = buildHomeReadModel(sources());
    const insight = model.priority!;
    expect(insight).toMatchObject({
      signalId: "sig_top",
      criterion: "Resolution clarity",
      domain: "Member Experience",
      failure: { failCount: 7, evaluatedResults: 12, failRateLabel: "58.3%", affectedEvaluations: 3, feedbackCount: 9 },
      humanValidation: { state: "awaiting_review" },
      evidenceReview: { state: "not_run" },
      reviewHref: "/agent-insights?signal=sig_top",
      nextStep: { label: "Review diagnosis" },
    });
    expect(insight.diagnosis).toMatchObject({
      state: "proposed",
      origin: "ai",
      causeDomain: "Skill Gap",
      performanceDimension: "Capability",
      confidence: { value: "0.78" },
    });
    expect((insight.diagnosis as { confidence: { wording: string } }).confidence.wording).toMatch(/not a statistically calibrated probability/);
    expect(insight.evidence).toMatchObject({ supporting: awaiting.provider_hypothesis.supporting_evidence, missing: ["Observe a live call"] });
  });

  it("recognizes a controlled fixture record as non-AI", () => {
    const model = buildHomeReadModel(sources({ priority: { signal: topSignal, record: fixtureRecord, validation: validatedReview, design: null } }));
    expect(model.priority!.diagnosis).toMatchObject({ state: "proposed", origin: "fixture" });
    expect(model.priority!.evidenceReview).toMatchObject({ state: "evidence_validated", origin: "fixture" });
  });

  it("reports no diagnosis when none was requested", () => {
    const model = buildHomeReadModel(sources({ priority: { signal: topSignal, record: null, validation: null, design: null } }));
    expect(model.priority!.diagnosis).toEqual({ state: "not_requested" });
    expect(model.priority!.evidenceReview).toEqual({ state: "not_applicable" });
    expect(model.priority!.humanValidation.state).toBe("none");
    expect(model.priority!.evidence).toBeNull();
    expect(model.priority!.nextStep.label).toBe("Request diagnostic hypothesis");
  });

  it("maps validated and questioned semantic reviews and ignores a review for another hypothesis", () => {
    const validated = buildHomeReadModel(sources({ priority: { signal: topSignal, record: awaiting, validation: validatedReview, design: null } }));
    expect(validated.priority!.evidenceReview).toMatchObject({ state: "evidence_validated", outcome: "Supported", unsupportedClaims: 0 });
    const questioned = buildHomeReadModel(sources({ priority: { signal: topSignal, record: awaiting, validation: questionedReview, design: null } }));
    expect(questioned.priority!.evidenceReview).toMatchObject({ state: "evidence_questioned", outcome: "Unsupported", unsupportedClaims: 1, missingEvidence: 1 });
    expect(questioned.priority!.humanValidation.state).toBe("awaiting_review");
    const foreign = buildHomeReadModel(sources({ priority: { signal: topSignal, record: awaiting, validation: { ...validatedReview, hypothesis_id: "hyp_other" }, design: null } }));
    expect(foreign.priority!.evidenceReview).toEqual({ state: "not_run" });
  });

  it("maps every human validation state with the recorded reviewer", () => {
    const state = (record: typeof awaiting) =>
      buildHomeReadModel(sources({ priority: { signal: topSignal, record, validation: null, design: null } })).priority!;
    expect(state(approved).humanValidation).toEqual({ state: "approved", reviewer: "qa-lead", rationale: null });
    expect(state(approved).nextStep.label).toBe("Design intervention");
    expect(state(revisedPending).humanValidation).toMatchObject({ state: "revised_pending", reviewer: "qa-2" });
    expect(state(revisedPending).nextStep.label).toBe("Approve human revision");
    expect(state(revisedPending).diagnosis).toMatchObject({ humanRevised: true, causeDomain: "Process Gap" });
    expect(state(revisedApproved).humanValidation).toMatchObject({ state: "revised_approved", reviewer: "qa-lead" });
    expect(state(rejected).humanValidation).toEqual({ state: "rejected", reviewer: "qa-3", rationale: "Evidence too thin" });
    expect(state(rejected).nextStep.label).toBe("Request another hypothesis");
  });

  it("shows an existing M5 proposal as proposed, never validated, and keeps alignment and outcome pending", () => {
    const training = buildHomeReadModel(sources({ priority: { signal: topSignal, record: approved, validation: null, design: designFixture("training") } }));
    expect(training.downstream.find((stage) => stage.id === "intervention")).toMatchObject({ status: "proposed", detail: expect.stringContaining("pending AWS-4") });
    expect(training.downstream.find((stage) => stage.id === "training")).toMatchObject({ status: "proposed", detail: expect.stringContaining("AWS-5") });
    expect(training.downstream.find((stage) => stage.id === "alignment")!.status).toBe("pending_backend");
    expect(training.downstream.find((stage) => stage.id === "outcome")!.status).toBe("pending_backend");
    expect(training.priority!.nextStep.label).toBe("Review proposed intervention");
    const nonTraining = buildHomeReadModel(sources({ priority: { signal: topSignal, record: approved, validation: null, design: designFixture("non_training") } }));
    expect(nonTraining.downstream.find((stage) => stage.id === "training")!.status).toBe("not_applicable");
    const validatedOnly = buildHomeReadModel(sources({ priority: { signal: topSignal, record: approved, validation: null, design: null } }));
    expect(validatedOnly.downstream.find((stage) => stage.id === "intervention")!.status).toBe("not_started");
  });

  it("validates the runtime mode shape", () => {
    expect(isRuntimeMode(realMode)).toBe(true);
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

  it("loads mode, signals, the top signal's latest record, its semantic review, and a design when validated", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      calls.push(path);
      if (path.endsWith("/mode")) return reply(demoMode);
      if (path.endsWith("/signals")) return reply([topSignal, secondSignal]);
      if (path.endsWith("/signals/sig_top/hypotheses")) return reply([approved, awaiting]);
      if (path.endsWith("/hypotheses/hyp_1/evidence-validation")) return reply(validatedReview);
      if (path.endsWith("/designs/diagnoses/hyp_1")) return reply(designFixture("training"));
      throw new Error(`Unexpected route ${path}`);
    }));
    const result = await loadHomeSources();
    expect(result.mode).toEqual(demoMode);
    expect(result.signals).toHaveLength(2);
    expect(result.priority).toMatchObject({ signal: topSignal, record: approved, validation: validatedReview });
    expect(result.priority!.design!.run_id).toBe("design_1");
    expect(calls.some((path) => path.includes("sig_second"))).toBe(false);
  });

  it("treats 404 for the semantic review and design as absent, and keeps other failures visible", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply([approved]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    const result = await loadHomeSources();
    expect(result.priority).toMatchObject({ record: approved, validation: null, design: null });

    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply({ detail: { code: "boom" } }, 500);
      throw new Error(`Unexpected route ${path}`);
    }));
    await expect(loadHomeSources()).rejects.toThrow(/could not be completed/);
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

  it("fails when the diagnostic service is unreachable instead of showing an empty team", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    await expect(loadHomeSources()).rejects.toThrow(/diagnostic service is unavailable/);
  });
});
