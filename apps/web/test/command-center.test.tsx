import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CommandCenter, { CommandCenterView } from "../app/command-center";
import { buildHomeReadModel } from "../lib/home/read-model";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";
import {
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

const priorityCard = () => screen.getByRole("region", { name: "Resolution clarity" });
const field = (name: string) => {
  const labelNode = within(priorityCard()).getByText(name, { selector: ".field-label" });
  return labelNode.parentElement as HTMLElement;
};
const pipelineStep = (name: string) => {
  const list = screen.getByRole("list", { name: "Progress of this insight through the workflow" });
  return within(list).getByText(name).parentElement as HTMLElement;
};
const downstreamCards = () =>
  within(screen.getByRole("region", { name: "Intervention, training, alignment, outcome" })).getAllByRole("listitem");

describe("Command Center view from a typed read-model", () => {
  it("renders summary, ranked gaps, the selected insight, and downstream slots from the model", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    expect(screen.getByRole("heading", { level: 1, name: "What needs attention across the team?" })).toBeInTheDocument();
    expect(screen.getByText(/Selected insight · first in backend failure-count order/)).toBeInTheDocument();
    expect(screen.queryByText(/highest priority/i)).not.toBeInTheDocument();
    const priority = screen.getByRole("article", { name: "Priority issues" });
    expect(within(priority).getByText("Pending")).toBeInTheDocument();
    expect(within(priority).getByText(/backend has not classified or prioritized issues/)).toBeInTheDocument();
    const gaps = screen.getByRole("region", { name: "Observed QA criteria" });
    const rows = within(gaps).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByRole("link", { name: "Resolution clarity" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(rows[0]).getByRole("img", { name: "Observed failure rate 58.3%" })).toBeInTheDocument();
    expect(within(rows[1]).getByRole("link", { name: "HIPAA verification" })).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(within(gaps).getByRole("link", { name: /All 3 observed signals/ })).toHaveAttribute("href", "/agent-insights");
    expect(screen.getByRole("region", { name: "Intervention, training, alignment, outcome" })).toBeInTheDocument();
  });

  it("shows an explicit no-data state with every tile pending and no statistics (B, Q)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ signals: [], priority: null, mode: null }))} />);
    expect(screen.getByText("No QA signals are loaded.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No observed criteria yet" })).toBeInTheDocument();
    for (const name of ["Agents monitored", "Priority issues", "Overall QA", "Training / intervention"]) {
      const tile = screen.getByRole("article", { name });
      expect(tile.querySelector(".stat-value")).toHaveTextContent("Pending");
      expect(tile.querySelector(".stat-note")).toBeNull();
      // Milestone names such as "M2" may appear; no count, rate, or percentage may.
      expect(tile.querySelector(".stat-detail")).not.toHaveTextContent(/\b\d+ (QA|evaluation|criteria|agent|issue)|\d+%|\d+\.\d/);
    }
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights");
    expect(screen.queryByRole("link", { name: "Continue in Agent Insights" })).not.toBeInTheDocument();
    const cards = downstreamCards();
    expect(within(cards[0]).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(cards[3]).getByText("Measurement pending")).toBeInTheDocument();
  });

  it("presents the selected insight as a working diagnosis with non-calibrated confidence and no training conclusion (D)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    const card = priorityCard();
    expect(within(card).getByText("58.3%")).toBeInTheDocument();
    expect(within(field("Performance issue")).getByText("7 of 12 criterion results failed")).toBeInTheDocument();
    expect(within(field("Performance issue")).getByText(/12 of 20 loaded evaluations contain this criterion · 9 with evaluator feedback/)).toBeInTheDocument();
    expect(within(field("Working diagnosis")).getByText("Agents close calls without confirming the next step.")).toBeInTheDocument();
    expect(within(field("Working diagnosis")).getByText(/AI proposal · not yet an intervention decision/)).toBeInTheDocument();
    expect(within(field("Working cause type")).getByText("Skill Gap · Capability")).toBeInTheDocument();
    expect(within(field("Working cause type")).getByText(/does not select training/)).toBeInTheDocument();
    expect(within(field("Model-reported confidence")).getByText("0.78")).toBeInTheDocument();
    expect(within(field("Model-reported confidence")).getByText(/not a statistically calibrated probability/)).toBeInTheDocument();
    expect(within(card).getByText("Failed rows show summaries that omit the follow-up action.")).toBeInTheDocument();
    expect(within(field("Evidence review")).getByText("Not yet reviewed")).toBeInTheDocument();
    expect(within(field("Human validation")).getByText("Awaiting human review")).toBeInTheDocument();
    expect(within(field("Intervention")).getByText("Requires human-validated diagnosis")).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(field("Alignment review")).getByText("Blocked upstream")).toBeInTheDocument();
    const preview = within(card).getByRole("region", { name: "Evidence preview" });
    expect(within(preview).getByText("Aggregate QA signal")).toBeInTheDocument();
    expect(within(preview).getByText("Evaluation eval_1")).toBeInTheDocument();
    expect(within(preview).getByText("Observe a live call")).toBeInTheDocument();
    expect(within(card).getByText("Review diagnosis")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(card).queryByText(/needs training/i)).not.toBeInTheDocument();
    expect(within(card).queryByText(/root cause/i)).not.toBeInTheDocument();
    expect(pipelineStep("Human validated")).toHaveTextContent("Awaiting review");
  });

  it("shows evidence validated as validated and evidence questioned as caution, never as rejection (E)", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ validation: validatedReview }) }))} />);
    const validatedPill = within(field("Evidence review")).getByText("Evidence validated · Supported");
    expect(validatedPill).toHaveClass("validated");
    expect(screen.getByText("The cited rows show the missing next-step summary.")).toBeInTheDocument();
    expect(within(field("Human validation")).getByText("Awaiting human review")).toBeInTheDocument();
    unmount();

    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ validation: questionedReview }) }))} />);
    const questionedPill = within(field("Evidence review")).getByText("Evidence questioned · Unsupported");
    expect(questionedPill).toHaveClass("caution");
    expect(questionedPill).not.toHaveClass("rejected");
    expect(within(field("Evidence review")).getByText(/Not a human decision/i)).toBeInTheDocument();
    expect(screen.getByText("The cited failures do not establish a skill gap.")).toBeInTheDocument();
    expect(screen.getByText(/1 claim beyond the evidence · 1 evidence gap noted/)).toBeInTheDocument();
    expect(within(field("Human validation")).getByText("Awaiting human review")).toBeInTheDocument();
    expect(pipelineStep("Evidence reviewed")).toHaveClass("caution");
    expect(screen.queryByText(/Rejected/)).not.toBeInTheDocument();
  });

  it("renders awaiting, approved, revised, and rejected human states with distinct tones", () => {
    const show = (record: typeof awaiting) => {
      const view = render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record }) }))} />);
      const pill = within(field("Human validation")).getByText((_, node) => node?.classList.contains("pill") ?? false);
      const text = pill.textContent;
      const classes = [...pill.classList];
      view.unmount();
      return { text, classes };
    };
    expect(show(awaiting)).toMatchObject({ text: "Awaiting human review", classes: expect.arrayContaining(["neutral"]) });
    expect(show(approved)).toMatchObject({ text: "Approved by qa-lead", classes: expect.arrayContaining(["validated"]) });
    expect(show(revisedPending)).toMatchObject({ text: "Revised · awaiting approval", classes: expect.arrayContaining(["caution"]) });
    expect(show(revisedApproved)).toMatchObject({ text: "Revision approved by qa-lead", classes: expect.arrayContaining(["validated"]) });
    expect(show(rejected)).toMatchObject({ text: "Rejected by qa-3", classes: expect.arrayContaining(["rejected"]) });
  });

  it("separates human approval from intervention and solution validation (F)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved }) }))} />);
    expect(within(field("Human validation")).getByText(/human decision on the diagnosis, not on any intervention/)).toBeInTheDocument();
    expect(within(field("Intervention")).getByText("Not proposed")).toBeInTheDocument();
    expect(within(field("Solution validation")).getByText("Not applicable yet")).toBeInTheDocument();
    expect(within(priorityCard()).getByText("Generate intervention")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(downstreamCards()[0]).getByText("Not started")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /propose|generate/i })).not.toBeInTheDocument();
  });

  it("shows a proposed AWS-4 intervention with solution validation pending (G)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", null) }) }))} />);
    expect(within(field("Intervention")).getByText("Training proposed · solution not validated")).toHaveClass("proposed");
    expect(within(field("Intervention")).getByText("Rehearse the closing summary in short simulated calls.")).toBeInTheDocument();
    expect(within(field("Intervention")).getByText(/Target change: State the next step/)).toBeInTheDocument();
    expect(within(field("Solution validation")).getByText("Awaiting validation")).toBeInTheDocument();
    expect(within(priorityCard()).getByText("Validate solution")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(pipelineStep("Intervention proposed")).toHaveTextContent("Training");
    expect(pipelineStep("Solution validated")).toHaveTextContent("Awaiting validation");
    expect(within(downstreamCards()[0]).getByRole("link", { name: /Validate solution/ })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("shows an aligned training intervention as permitted, not generated, and never as alignment (H)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "aligned") }) }))} />);
    expect(within(field("Intervention")).getByText("Training · solution validated")).toHaveClass("validated");
    expect(within(field("Solution validation")).getByText("Solution validated · Aligned")).toHaveClass("validated");
    expect(within(field("Solution validation")).getByText(/Not a human approval, and not training alignment/)).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Ready to generate · not generated")).toHaveClass("pending");
    expect(within(field("Alignment review")).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(priorityCard()).getByText("Generate training")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(downstreamCards()[1]).getByRole("link", { name: /Generate training/ })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("shows a questioned solution as caution with training withheld (I)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("training", "misaligned") }) }))} />);
    const solution = within(field("Solution validation")).getByText("Solution questioned · Misaligned");
    expect(solution).toHaveClass("caution");
    expect(solution).not.toHaveClass("rejected");
    expect(within(field("Solution validation")).getByText("Training does not address the validated cause.")).toBeInTheDocument();
    expect(within(field("Training package")).getByText("Training withheld")).toHaveClass("caution");
    expect(pipelineStep("Solution validated")).toHaveTextContent("Questioned");
    expect(pipelineStep("Training generated")).toHaveTextContent("Withheld");
    expect(within(priorityCard()).getByText("Review solution concerns")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(downstreamCards()[1]).getByText("Withheld")).toBeInTheDocument();
    expect(screen.queryByText(/Rejected/)).not.toBeInTheDocument();
  });

  it("shows a validated process correction with training not applicable, not failed (J)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("process_correction", "aligned"), design: designFixture("non_training") }) }))} />);
    expect(within(field("Intervention")).getByText("Process Correction · solution validated")).toHaveClass("validated");
    const training = within(field("Training package")).getByText("Training not applicable");
    expect(training).toHaveClass("not_applicable");
    expect(training).not.toHaveClass("caution");
    expect(within(field("Training package")).getByText(/does not call for training, so no package is generated/)).toBeInTheDocument();
    expect(pipelineStep("Training generated")).toHaveTextContent("Not applicable");
    expect(pipelineStep("Training generated")).not.toHaveClass("caution");
    expect(pipelineStep("Alignment")).toHaveTextContent("Not applicable");
    expect(within(priorityCard()).getByText("Review validated process intervention")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(downstreamCards()[1]).getByText("Not applicable")).toBeInTheDocument();
    expect(screen.queryByText(/withheld|failed training/i)).not.toBeInTheDocument();
  });

  it("shows a generated AWS-5 package as generated, not deployed, with alignment pending (K, N)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ record: approved, intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage() }) }))} />);
    expect(within(field("Training package")).getByText("Training generated · not deployed")).toHaveClass("validated");
    expect(within(field("Training package")).getByText("State next step and check understanding")).toBeInTheDocument();
    expect(within(field("Training package")).getByText(/1 outline section · 1 activity · 1 knowledge check · 1 practice scenario · 12 min planned · 1 operational detail still needed/)).toBeInTheDocument();
    expect(within(field("Training package")).getByRole("link", { name: "Open training package" })).toHaveAttribute("href", "/training?signal=sig_top");
    expect(within(field("Training package")).getByRole("link", { name: "Open role-play script" })).toHaveAttribute("href", "/role-play?signal=sig_top");
    expect(within(field("Alignment review")).getByText("Pending · not yet reviewed")).toHaveClass("pending");
    expect(pipelineStep("Training generated")).toHaveTextContent("Generated");
    expect(pipelineStep("Alignment")).toHaveTextContent("Pending");
    expect(within(priorityCard()).getByText("Review training package")).toHaveAttribute("href", "/training?signal=sig_top");
    const cards = downstreamCards();
    expect(within(cards[1]).getByText("Generated · not deployed")).toBeInTheDocument();
    expect(within(cards[1]).getByRole("link", { name: /Open training package/ })).toHaveAttribute("href", "/training?signal=sig_top");
    expect(within(cards[2]).getByText("Pending · not yet reviewed")).toBeInTheDocument();
    expect(within(cards[2]).getByText("Source: AWS-6 alignment review")).toBeInTheDocument();
    expect(within(cards[3]).getByText("Measurement pending")).toBeInTheDocument();
    expect(within(cards[3]).getByRole("link", { name: /Open KPI Tracker/ })).toHaveAttribute("href", "/kpi-tracker");
    expect(within(cards[3]).queryByText(/%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/improve/i)).not.toBeInTheDocument();
    const tile = screen.getByRole("article", { name: "Training / intervention" });
    expect(within(tile).getByText("Pending")).toBeInTheDocument();
    expect(within(tile).getByText("Selected insight: training package generated, alignment pending")).toBeInTheDocument();
  });

  it("routes the primary CTA into the existing analysis workspace on the summarized signal (C)", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: insight({ signal: secondSignal, record: null }) }))} />);
    const cta = screen.getByRole("link", { name: "Continue in Agent Insights" });
    expect(cta).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(cta).toHaveClass("primary");
    expect(screen.getByText("Review observed evidence and run diagnosis")).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(pipelineStep("Diagnosed")).toHaveTextContent("Not requested");
  });

  it("separates synthetic demo provenance from real ResultsCX provenance", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources({ mode: demoMode, priority: insight({ record: fixtureRecord }) }))} />);
    const badge = screen.getByRole("note", { name: "Data provenance" });
    expect(within(badge).getByText("Synthetic demo")).toBeInTheDocument();
    expect(within(badge).getByText(/Nothing here is ResultsCX output/)).toBeInTheDocument();
    expect(within(badge).getByText(/Intervention provider: controlled_fixture/)).toBeInTheDocument();
    expect(within(field("Working diagnosis")).getByText(/Controlled non-AI fixture proposal/)).toBeInTheDocument();
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

describe("Command Center data states", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows loading, then renders real backend data", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([topSignal, secondSignal]);
      if (path.endsWith("/hypotheses")) return reply([awaiting]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    render(<CommandCenter />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading team summary");
    expect(await screen.findByRole("region", { name: "Resolution clarity" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue in Agent Insights" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.getByText("Real ResultsCX · local")).toBeInTheDocument();
  });

  it("reloads the read-model from the backend on refresh, picking up AWS-4 state", async () => {
    let records = [awaiting];
    let intervention: unknown = null;
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(demoMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply(records);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/interventions/")) return intervention ? reply(intervention) : reply({ detail: { code: "intervention_not_found" } }, 404);
      if (path.includes("/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    render(<CommandCenter />);
    expect(await screen.findByText("Awaiting human review")).toBeInTheDocument();
    records = [approved];
    intervention = interventionFixture("training", "aligned", { fixture: true });
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("Approved by qa-lead")).toBeInTheDocument();
    expect(screen.getByText("Training · solution validated")).toBeInTheDocument();
    expect(screen.getByText("Generate training")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.queryByText("Awaiting human review")).not.toBeInTheDocument();
  });

  it("shows an error with a retry and a route into Agent Insights when the service is unavailable (A)", async () => {
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
