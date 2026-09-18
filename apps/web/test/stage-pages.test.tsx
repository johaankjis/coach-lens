import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import KpiTrackerPage from "../app/kpi-tracker/page";
import RolePlayPage from "../app/role-play/page";
import TrainingPage from "../app/training/page";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";
import { approved, awaiting, demoMode, providerPackage, realMode, secondSignal, topSignal } from "./home.test-fixture";

function reply(value: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => value } as Response;
}

type Backend = {
  records?: unknown[];
  intervention?: unknown;
  design?: unknown;
  signals?: unknown[];
  mode?: unknown;
};

function route({ records = [approved], intervention = null, design = null, signals = [topSignal, secondSignal], mode = realMode }: Backend = {}) {
  const mock = vi.fn(async (path: string) => {
    if (path.endsWith("/mode")) return reply(mode);
    if (path.endsWith("/signals")) return reply(signals);
    if (path.endsWith("/sig_top/hypotheses")) return reply(records);
    if (path.endsWith("/sig_second/hypotheses")) return reply([]);
    if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
    if (path.includes("/interventions/")) return intervention ? reply(intervention) : reply({ detail: { code: "intervention_not_found" } }, 404);
    if (path.includes("/designs/")) return design ? reply(design) : reply({ detail: { code: "design_not_found" } }, 404);
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const params = (signal?: string) => ({ searchParams: Promise.resolve(signal ? { signal } : {}) });

describe("Training page", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the real AWS-5 package with its validated intervention context (L)", async () => {
    route({ intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage() });
    render(await TrainingPage(params("sig_top")));
    expect(screen.getByRole("heading", { level: 1, name: "Generated training package" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Resolution clarity" })).toBeInTheDocument();
    const context = screen.getByRole("region", { name: "Resolution clarity" });
    expect(within(context).getByText("Practice Simulation · solution validated")).toHaveClass("validated");
    expect(within(context).getByText("Rehearse the closing summary in short simulated calls.")).toBeInTheDocument();
    expect(within(context).getByText(/Target change: State the next step/)).toBeInTheDocument();
    expect(within(context).getByText("Training generated · not deployed")).toBeInTheDocument();
    expect(within(context).getByText(/Design status: ready for alignment review/)).toBeInTheDocument();
    expect(within(context).getByText("Pending · not yet reviewed")).toBeInTheDocument();
    expect(within(context).getByText(/human validated by qa-lead/)).toBeInTheDocument();
    // The package itself, rendered by the existing design workspace.
    expect(screen.getByRole("region", { name: "Proposed intervention design" })).toBeInTheDocument();
    expect(screen.getByText("READY FOR ALIGNMENT REVIEW")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What this package was designed from" })).toBeInTheDocument();
    expect(screen.getByText("State next step and check understanding")).toBeInTheDocument();
    expect(screen.getByText("Summarize and confirm on a simulated call")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Learning plan" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Model and rehearse" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What the learner will do" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Decision checks" })).toBeInTheDocument();
    expect(screen.getByText("What should the representative do before closing?")).toBeInTheDocument();
    expect(screen.getByText("[PLACEHOLDER:M1]")).toBeInTheDocument();
    // Practice lives on the Role-Play page.
    expect(screen.queryByRole("heading", { name: "The practice CoachLens proposed" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open role-play script" })[0]).toHaveAttribute("href", "/role-play?signal=sig_top");
    expect(screen.queryByRole("button", { name: /design|generate|deploy|assign/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/improvement|has been deployed/i)).not.toBeInTheDocument();
  });

  it("explains training withheld for a questioned solution without a training failure (I)", async () => {
    route({ intervention: interventionFixture("training", "misaligned") });
    render(await TrainingPage(params("sig_top")));
    expect(await screen.findByRole("heading", { level: 2, name: "Training withheld" })).toBeInTheDocument();
    expect(screen.getAllByText(/questioned the training proposal, so training design is withheld/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(screen.queryByRole("region", { name: "Proposed intervention design" })).not.toBeInTheDocument();
  });

  it("explains training not applicable for a validated process correction (J)", async () => {
    route({ intervention: interventionFixture("process_correction", "aligned"), design: designFixture("non_training") });
    render(await TrainingPage(params("sig_top")));
    expect(await screen.findByRole("heading", { level: 2, name: "Training not applicable" })).toBeInTheDocument();
    expect(screen.getByText(/not a failed training stage/)).toBeInTheDocument();
    expect(screen.getByText("Review validated process intervention")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("states that nothing is generated for an unvalidated diagnosis and falls back on an unknown signal (O)", async () => {
    const mock = route({ records: [awaiting] });
    render(await TrainingPage(params("sig_missing")));
    expect(await screen.findByRole("heading", { level: 2, name: "No training package" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Requested signal is unavailable");
    expect(screen.getByRole("heading", { level: 2, name: "Resolution clarity" })).toBeInTheDocument();
    expect(mock).not.toHaveBeenCalledWith(expect.stringContaining("sig_missing"), expect.anything());
  });

  it("shows an error with retry when the backend is unavailable (A)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    render(await TrainingPage(params()));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The diagnostic service is unavailable.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(within(alert).getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/");
  });
});

describe("Role-Play page", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the generated practice as a full facilitator script (M)", async () => {
    route({ intervention: interventionFixture("practice_simulation", "aligned"), design: providerPackage() });
    render(await RolePlayPage(params("sig_top")));
    expect(screen.getByRole("heading", { level: 1, name: "Hands-on practice script" })).toBeInTheDocument();
    const script = await screen.findByRole("article", { name: "Follow-up call" });
    expect(within(script).getByText("AI-generated practice specification")).toBeInTheDocument();
    expect(within(script).getByText("Learner role: Representative")).toBeInTheDocument();
    expect(within(script).getByText("Morgan")).toBeInTheDocument();
    expect(within(script).getByText(/Fictional persona · Synthetic member · Direct · Concerned/)).toBeInTheDocument();
    expect(within(script).getByText("“What happens next?”")).toBeInTheDocument();
    expect(within(script).getByText("Facilitator plays the member with the request status visible.")).toBeInTheDocument();
    expect(within(script).getByText("Confirm understanding")).toBeInTheDocument();
    expect(within(script).getByText("No escalation procedure was supplied, so none is scripted.")).toBeInTheDocument();
    expect(within(script).getByText("State next step and check understanding")).toBeInTheDocument();
    // Scripted turns are open on the page, not behind a disclosure.
    const turns = within(script).getByRole("region", { name: "Scripted turns" });
    expect(within(turns).getAllByRole("listitem")).toHaveLength(2);
    expect(within(turns).getByText("Persona: “When will that happen?”")).toBeInTheDocument();
    expect(within(turns).getByText("Name the specific next action.")).toBeInTheDocument();
    expect(within(turns).getByText("Listen for a confirming question.")).toBeInTheDocument();
    expect(within(turns).getByText("Watch for invented timing.")).toBeInTheDocument();
    expect(within(script).getByRole("region", { name: "Completion criteria" })).toHaveTextContent("Member confirms");
    expect(within(script).getByText("Summarize and confirm")).toBeInTheDocument();
    expect(within(script).getByText("Scoring guidance: Met if both occur")).toBeInTheDocument();
    expect(within(script).getByText("What was clear?")).toBeInTheDocument();
    expect(within(script).getByText(/No learner has been scored/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Open training package" })[0]).toHaveAttribute("href", "/training?signal=sig_top");
    expect(screen.queryByRole("button", { name: /start|run|simulate|score/i })).not.toBeInTheDocument();
  });

  it("explains that no practice exists before a package is generated", async () => {
    route({ intervention: interventionFixture("training", "aligned") });
    render(await RolePlayPage(params("sig_top")));
    expect(await screen.findByRole("heading", { level: 2, name: "No practice scenario yet" })).toBeInTheDocument();
    expect(screen.getAllByText(/No training package has been generated yet/).length).toBeGreaterThan(0);
    expect(screen.getByText("Generate training")).toHaveAttribute("href", "/agent-insights?signal=sig_top");
  });

  it("marks practice not applicable for a non-training intervention", async () => {
    route({ intervention: interventionFixture("coaching", "aligned") });
    render(await RolePlayPage(params()));
    expect(await screen.findByRole("heading", { level: 2, name: "Practice not applicable" })).toBeInTheDocument();
  });
});

describe("KPI Tracker page", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps outcome measurement pending over the observed baseline and shows no improvement (N)", async () => {
    route({ mode: demoMode, intervention: interventionFixture("training", "aligned", { fixture: true }), design: designFixture("training") });
    render(<KpiTrackerPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Outcome measurement pending" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 2, name: "Observed criteria at baseline" })).toBeInTheDocument();
    const status = screen.getByRole("region", { name: "Nothing to compare yet" });
    expect(within(status).getByText(/Synthetic demo\. 2 observed criteria/)).toBeInTheDocument();
    expect(within(status).getByText(/A training package is generated for the selected insight\. It has not been delivered\./)).toBeInTheDocument();
    expect(within(status).getByText(/Pending\. No follow-up evaluations have been loaded\./)).toBeInTheDocument();
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByRole("link", { name: "Resolution clarity" })).toHaveAttribute("href", "/agent-insights?signal=sig_top");
    expect(within(rows[1]).getByText("7 / 12")).toBeInTheDocument();
    expect(within(rows[1]).getByText("58.3%")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Pending")).toBeInTheDocument();
    expect(within(rows[2]).getByText("25.0%")).toBeInTheDocument();
    expect(screen.queryByText(/\d+(\.\d+)?% (improvement|reduction|increase)|improved|reduced by|\+\d/i)).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button").map((button) => button.textContent)).toEqual(["Refresh"]);
  });

  it("shows an empty baseline explicitly when no QA is loaded (B)", async () => {
    route({ signals: [], mode: { ...realMode, evaluation_count: 0, signal_count: 0 } });
    render(<KpiTrackerPage />);
    expect(await screen.findByText("No QA signals are loaded.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});
