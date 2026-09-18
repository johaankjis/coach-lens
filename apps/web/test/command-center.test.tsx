import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CommandCenter, { CommandCenterView } from "../app/command-center";
import { buildHomeReadModel } from "../lib/home/read-model";
import { designFixture } from "./design-workspace.test-fixture";
import {
  approved,
  awaiting,
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

const priorityCard = () => screen.getByRole("region", { name: "Resolution clarity" });
const field = (name: string) => {
  const labelNode = within(priorityCard()).getByText(name, { selector: ".field-label" });
  return labelNode.parentElement as HTMLElement;
};

describe("Command Center view from a typed read-model", () => {
  it("renders summary, ranked gaps, the priority insight, and downstream slots from the model", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    expect(screen.getByRole("heading", { level: 1, name: "What needs attention across the team?" })).toBeInTheDocument();
    const priority = screen.getByRole("article", { name: "Priority issues" });
    expect(within(priority).getByText("2")).toBeInTheDocument();
    expect(within(priority).getByText(/of 3 observed criteria have failed results/)).toBeInTheDocument();
    const gaps = screen.getByRole("region", { name: "Top performance gaps" });
    const rows = within(gaps).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByRole("link", { name: "Resolution clarity" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(rows[0]).getByRole("img", { name: "Observed failure rate 58.3%" })).toBeInTheDocument();
    expect(within(rows[1]).getByRole("link", { name: "HIPAA verification" })).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(within(gaps).getByRole("link", { name: /All 3 observed signals/ })).toHaveAttribute("href", "/agent-insights");
    expect(screen.getByRole("region", { name: "Intervention, training, alignment, outcome" })).toBeInTheDocument();
  });

  it("shows an explicit no-data state without a priority insight", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ signals: [], priority: null, mode: { ...realMode, evaluation_count: 0, signal_count: 0 } }))} />);
    expect(screen.getByText("No QA signals are loaded.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Nothing to prioritize yet" })).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Priority issues" })).getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights");
    expect(screen.queryByRole("link", { name: "Review Evidence & Validate" })).not.toBeInTheDocument();
  });

  it("presents the priority insight as a working diagnosis with non-calibrated confidence and no training conclusion", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    const card = priorityCard();
    expect(within(card).getByText("58.3%")).toBeInTheDocument();
    expect(within(field("Performance issue")).getByText("7 of 12 criterion results failed")).toBeInTheDocument();
    expect(within(field("Performance issue")).getByText(/12 of 20 loaded evaluations contain this criterion/)).toBeInTheDocument();
    expect(within(field("Working diagnosis")).getByText("Agents close calls without confirming the next step.")).toBeInTheDocument();
    expect(within(field("Working diagnosis")).getByText(/AI proposal · not yet an intervention decision/)).toBeInTheDocument();
    expect(within(field("Working cause type")).getByText("Skill Gap · Capability")).toBeInTheDocument();
    expect(within(field("Working cause type")).getByText(/does not select training/)).toBeInTheDocument();
    expect(within(field("Model-reported confidence")).getByText("0.78")).toBeInTheDocument();
    expect(within(field("Model-reported confidence")).getByText(/not a statistically calibrated probability/)).toBeInTheDocument();
    expect(within(card).getByText("Failed rows show summaries that omit the follow-up action.")).toBeInTheDocument();
    expect(within(field("Evidence review")).getByText("Not yet reviewed")).toBeInTheDocument();
    expect(within(field("Human validation")).getByText("Awaiting human review")).toBeInTheDocument();
    const preview = within(card).getByRole("region", { name: "Evidence preview" });
    expect(within(preview).getByText("Aggregate QA signal")).toBeInTheDocument();
    expect(within(preview).getByText("Evaluation eval_1")).toBeInTheDocument();
    expect(within(preview).getByText("Observe a live call")).toBeInTheDocument();
    expect(within(card).getByText("Review diagnosis")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(card).queryByText(/needs training/i)).not.toBeInTheDocument();
    expect(within(card).queryByText(/root cause/i)).not.toBeInTheDocument();
  });

  it("shows evidence validated as validated and evidence questioned as caution, never as rejection", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources({ priority: { signal: topSignal, record: awaiting, validation: validatedReview, design: null } }))} />);
    const validatedPill = within(field("Evidence review")).getByText("Evidence validated · Supported");
    expect(validatedPill).toHaveClass("validated");
    expect(screen.getByText("The cited rows show the missing next-step summary.")).toBeInTheDocument();
    expect(within(field("Human validation")).getByText("Awaiting human review")).toBeInTheDocument();
    unmount();

    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: { signal: topSignal, record: awaiting, validation: questionedReview, design: null } }))} />);
    const questionedPill = within(field("Evidence review")).getByText("Evidence questioned · Unsupported");
    expect(questionedPill).toHaveClass("caution");
    expect(questionedPill).not.toHaveClass("rejected");
    expect(within(field("Evidence review")).getByText(/Not a human decision/)).toBeInTheDocument();
    expect(screen.getByText("The cited failures do not establish a skill gap.")).toBeInTheDocument();
    expect(screen.getByText(/1 claim beyond the evidence · 1 evidence gap noted/)).toBeInTheDocument();
    expect(within(field("Human validation")).getByText("Awaiting human review")).toBeInTheDocument();
    expect(screen.queryByText(/Rejected/)).not.toBeInTheDocument();
  });

  it("renders awaiting, approved, revised, and rejected human states with distinct tones", () => {
    const show = (record: typeof awaiting) => {
      const view = render(<CommandCenterView model={buildHomeReadModel(sources({ priority: { signal: topSignal, record, validation: null, design: null } }))} />);
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

  it("routes the primary CTA into the existing analysis workspace on the summarized signal", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: { signal: secondSignal, record: null, validation: null, design: null } }))} />);
    const cta = screen.getByRole("link", { name: "Review Evidence & Validate" });
    expect(cta).toHaveAttribute("href", "/agent-insights?signal=sig_second");
    expect(cta).toHaveClass("primary");
    expect(screen.getByText("Request diagnostic hypothesis")).toHaveAttribute("href", "/agent-insights?signal=sig_second");
  });

  it("renders intervention, training, alignment, and outcome as pending or blocked, never as values", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources())} />);
    const downstream = screen.getByRole("region", { name: "Intervention, training, alignment, outcome" });
    const cards = within(downstream).getAllByRole("listitem");
    expect(cards.map((card) => within(card).getByRole("heading", { level: 3 }).textContent)).toEqual(["Intervention", "Training", "Alignment", "Outcome"]);
    expect(within(cards[0]).getByText("Blocked upstream")).toBeInTheDocument();
    expect(within(cards[2]).getByText("Pending backend")).toBeInTheDocument();
    expect(within(cards[2]).getByText("Source: AWS-6 alignment review")).toBeInTheDocument();
    expect(within(cards[3]).getByText("Pending backend")).toBeInTheDocument();
    const tile = screen.getByRole("article", { name: "Training / intervention" });
    expect(within(tile).getByText("Pending")).toBeInTheDocument();
    expect(within(tile).getByText(/not merged yet/)).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Agents monitored" })).getByText("Pending")).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Overall QA" })).getByText("Pending")).toBeInTheDocument();
    expect(within(downstream).queryByText(/%/)).not.toBeInTheDocument();
  });

  it("labels an existing M5 proposal as proposed and not validated", () => {
    render(<CommandCenterView model={buildHomeReadModel(sources({ priority: { signal: topSignal, record: approved, validation: null, design: designFixture("training") } }))} />);
    const downstream = screen.getByRole("region", { name: "Intervention, training, alignment, outcome" });
    expect(within(downstream).getAllByText("Proposed · not validated")).toHaveLength(2);
    expect(within(downstream).getByText(/M5 proposed Training \(Ready For Alignment Review\)\. Validation of that proposal is pending AWS-4\./)).toBeInTheDocument();
  });

  it("separates synthetic demo provenance from real ResultsCX provenance", () => {
    const { unmount } = render(<CommandCenterView model={buildHomeReadModel(sources({ mode: demoMode, priority: { signal: topSignal, record: fixtureRecord, validation: null, design: null } }))} />);
    const badge = screen.getByRole("note", { name: "Data provenance" });
    expect(within(badge).getByText("Synthetic demo")).toBeInTheDocument();
    expect(within(badge).getByText(/Nothing here is ResultsCX output/)).toBeInTheDocument();
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
    expect(screen.getByRole("link", { name: "Review Evidence & Validate" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.getByText("Real ResultsCX · local")).toBeInTheDocument();
  });

  it("reloads the read-model from the backend on refresh", async () => {
    let records = [awaiting];
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path.endsWith("/mode")) return reply(demoMode);
      if (path.endsWith("/signals")) return reply([topSignal]);
      if (path.endsWith("/hypotheses")) return reply(records);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      throw new Error(`Unexpected route ${path}`);
    }));
    render(<CommandCenter />);
    // The state appears in the pipeline strip and in the human validation field.
    expect(await screen.findAllByText("Awaiting human review")).toHaveLength(2);
    records = [approved];
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findAllByText("Approved by qa-lead")).toHaveLength(2);
    expect(screen.queryByText("Awaiting human review")).not.toBeInTheDocument();
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
    mock.mockImplementation(async (path: string) => {
      if (path.endsWith("/mode")) return reply(realMode);
      if (path.endsWith("/signals")) return reply([]);
      throw new Error(`Unexpected route ${path}`);
    });
    await userEvent.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No QA signals are loaded.")).toBeInTheDocument();
  });
});
