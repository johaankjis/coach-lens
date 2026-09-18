import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReviewWorkspace from "../app/review-workspace";
import type { EvidenceBundle, EvidenceValidation, RecordState, Signal } from "../lib/diagnostics";
import { designFixture } from "./design-workspace.test-fixture";
import { interventionFixture } from "./intervention-workspace.test-fixture";

const signal: Signal = {
  signal_id: "sig_1",
  domain: "member_experience",
  criterion: "Resolution clarity",
  evaluated_results: 2,
  evaluated_evaluations: 2,
  total_evaluations: 3,
  pass_count: 1,
  fail_count: 1,
  fail_rate: "0.5",
  feedback_count: 2,
  affected_evaluation_ids: ["eval_1"],
};
const evidence: EvidenceBundle = {
  signal,
  items: [
    {
      item_id: "ev_1",
      evaluation_id: "eval_1",
      domain: signal.domain,
      criterion: signal.criterion,
      passed: false,
      answer: "No",
      max_score: "10",
      attained_score: "2",
      evaluator_feedback: "Next step unclear",
      source_lineage: {
        source_filename: "synthetic.xlsx",
        source_sheet: "QA",
        excel_row: 2,
      },
    },
    {
      item_id: "ev_2",
      evaluation_id: "eval_2",
      domain: signal.domain,
      criterion: signal.criterion,
      passed: true,
      answer: "Yes",
      max_score: "10",
      attained_score: "10",
      evaluator_feedback: "Clear summary",
      source_lineage: {
        source_filename: "synthetic.xlsx",
        source_sheet: "QA",
        excel_row: 3,
      },
    },
  ],
};
const proposed: RecordState = {
  provider_hypothesis: {
    hypothesis_id: "hyp_1",
    signal_id: signal.signal_id,
    observed_behavioral_defect: "One source QA result failed",
    cause_domain: "skill_gap",
    performance_dimension: "capability",
    explanation: "Provider proposed a skill gap.",
    supporting_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }],
    conflicting_evidence: [{ item_id: "ev_2", evaluation_id: "eval_2" }],
    missing_evidence: ["Observe a live call"],
    provider_reported_confidence: "0.78",
    provider_metadata: { provider: "test-provider", model: null },
  },
  status: "awaiting_review",
  human_revision: null,
  revision_approved: false,
  events: [],
};

function reply(value: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => value } as Response;
}
function route(
  records: RecordState[] = [proposed],
  mutation?: (path: string, init?: RequestInit) => Promise<Response>,
) {
  const mock = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST" && mutation) return mutation(path, init);
    if (path.endsWith("/signals")) return reply([signal]);
    if (path.endsWith("/review-evidence")) return reply(evidence);
    if (path.endsWith("/hypotheses")) return reply(records);
    if (path.endsWith("/hypotheses/hyp_1")) return reply(records[0]);
    if (path.endsWith("/evidence-validation")) return storedValidation
      ? reply(storedValidation) : reply({ detail: { code: "validation_not_found" } }, 404);
    if (path.includes("/api/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
    if (path.includes("/api/interventions/")) return reply({ detail: { code: "intervention_not_found" } }, 404);
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
const questionedValidation: EvidenceValidation = {
  validation_id: "val_1", hypothesis_id: "hyp_1", signal_id: "sig_1",
  assessed_proposal: "provider_hypothesis",
  validation_outcome: "unsupported", semantic_status: "evidence_questioned",
  support_assessment: "The cited failures do not establish a skill gap.",
  supported_reference_ids: ["EVID-001"], contradicting_reference_ids: ["EVID-002"],
  supported_evidence: [{ item_id: "ev_1", evaluation_id: "eval_1" }],
  contradicting_evidence: [{ item_id: "ev_2", evaluation_id: "eval_2" }],
  unsupported_claims: ["Skill gap is unproven"], missing_evidence: ["Direct observation"],
  provider_reported_confidence: 0.2,
};
let storedValidation: EvidenceValidation | null = null;
async function loaded() {
  await screen.findByText("Provider proposed a skill gap.");
}
beforeEach(() => {
  vi.unstubAllGlobals();
  storedValidation = null;
});

describe("diagnostic review semantics", () => {
  it("shows a questioned evidence review separately from human approval", async () => {
    const mock = route([proposed], async (path) => {
      if (path.endsWith("/validate-evidence")) return reply(questionedValidation);
      throw new Error(`Unexpected route ${path}`);
    });
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Validate evidence" }));
    expect(await screen.findByText("The cited failures do not establish a skill gap.")).toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Semantic evidence review" });
    expect(within(panel).getByText("Unsupported")).toBeInTheDocument();
    expect(within(panel).getByText("EVIDENCE QUESTIONED")).toBeInTheDocument();
    expect(within(panel).getByText("Skill gap is unproven")).toBeInTheDocument();
    expect(within(panel).getByText("Direct observation")).toBeInTheDocument();
    expect(within(panel).getByText("0.2")).toBeInTheDocument();
    expect(within(panel).getByText(/does not approve or reject the diagnosis/)).toBeInTheDocument();
    // Human controls remain, and nothing reads as human validated or rejected.
    expect(screen.getByText("This diagnosis has not been human validated.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve diagnosis" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revise" })).toBeInTheDocument();
    expect(screen.queryByText("HUMAN VALIDATED")).not.toBeInTheDocument();
    expect(screen.queryByText("REJECTED")).not.toBeInTheDocument();
    expect(mock).toHaveBeenCalledWith(expect.stringContaining("/validate-evidence"), expect.objectContaining({ method: "POST" }));
  });

  it("opens the validator's contradicting evidence in the inspector by local reference", async () => {
    route([proposed], async (path) => {
      if (path.endsWith("/validate-evidence")) return reply(questionedValidation);
      throw new Error(`Unexpected route ${path}`);
    });
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: "Validate evidence" }));
    const panel = await screen.findByRole("region", { name: "Semantic evidence review" });
    const contradicting = within(panel).getByRole("region", { name: "Evidence the validator finds contradicting" });
    await userEvent.click(within(contradicting).getByRole("button", { name: /Evaluation eval_2/ }));
    expect(screen.getByText("Yes · Pass")).toBeInTheDocument();
    expect(screen.getByText("Clear summary")).toBeInTheDocument();
    // Opaque wire references are never what the reviewer navigates by.
    expect(within(panel).queryByText(/EVID-00/)).not.toBeInTheDocument();
  });

  it("loads a stored review on selection and reads it as the original proposal's review after a revision", async () => {
    storedValidation = questionedValidation;
    route([{
      ...proposed,
      status: "revised",
      human_revision: {
        ...proposed.provider_hypothesis,
        cause_domain: "process_gap",
        performance_dimension: "undetermined",
        explanation: "Reviewer found a process issue.",
      },
      events: [{ action: "revise", reviewer_id: "qa-1", occurred_at: "2026-09-17T12:00:00Z", rationale: "Process evidence" }],
    }]);
    render(<ReviewWorkspace />);
    await loaded();
    const panel = await screen.findByRole("region", { name: "Semantic evidence review" });
    expect(await within(panel).findByText("The cited failures do not establish a skill gap.")).toBeInTheDocument();
    expect(within(panel).getByText(/assessed the original proposal only/)).toBeInTheDocument();
    expect(within(panel).getByText(/revision below has not been semantically reviewed/)).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Validate evidence" })).not.toBeInTheDocument();
    expect(screen.getByText("Reviewer found a process issue.")).toBeInTheDocument();
  });

  it("does not offer semantic validation after a human decision without a stored review", async () => {
    route([{ ...proposed, status: "approved", events: [{ action: "approve", reviewer_id: "qa-1", occurred_at: "2026-09-17T12:00:00Z", rationale: null }] }]);
    render(<ReviewWorkspace />);
    await loaded();
    const panel = screen.getByRole("region", { name: "Semantic evidence review" });
    expect(await within(panel).findByText("No semantic evidence review was recorded before the reviewer’s decision.")).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Validate evidence" })).not.toBeInTheDocument();
    expect(screen.getByText("HUMAN VALIDATED")).toBeInTheDocument();
  });

  it("labels deterministic observations and an unvalidated proposal, without probability language", async () => {
    route();
    render(<ReviewWorkspace />);
    await loaded();
    expect(
      screen.getByText(/OBSERVED · DETERMINISTIC QA SIGNAL/),
    ).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(
      screen.getByText("loaded evaluations contain this criterion"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("50.0%").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/AI-GENERATED · DIAGNOSTIC HYPOTHESIS/),
    ).toBeInTheDocument();
    expect(screen.getByText("NOT YET VALIDATED")).toBeInTheDocument();
    expect(screen.getByText("0.78")).toBeInTheDocument();
    expect(
      screen.getByText(/not a statistically calibrated probability/),
    ).toBeInTheDocument();
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
  });

  it("opens supporting and conflicting citations with source lineage", async () => {
    route();
    render(<ReviewWorkspace />);
    await loaded();
    const support = within(
      screen.getByRole("region", { name: "Supporting evidence" }),
    ).getByRole("button");
    await userEvent.click(support);
    expect(screen.getByText("Next step unclear")).toBeInTheDocument();
    expect(screen.getByText(/synthetic.xlsx · QA · 2/)).toBeInTheDocument();
    const conflict = within(
      screen.getByRole("region", { name: "Conflicting evidence" }),
    ).getByRole("button");
    await userEvent.click(conflict);
    expect(screen.getByText("Clear summary")).toBeInTheDocument();
    expect(screen.getByText(/synthetic.xlsx · QA · 3/)).toBeInTheDocument();
    expect(
      screen.getByText(/Conflicting evidence is present/),
    ).toBeInTheDocument();
  });

  it("shows validated state only after the backend approves", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const mock = route([proposed], async (path) => {
      expect(path.endsWith("/approve")).toBe(true);
      return pending;
    });
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.type(
      screen.getByPlaceholderText("Your reviewer ID"),
      "supervisor-1",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Approve diagnosis" }),
    );
    expect(screen.getByText("NOT YET VALIDATED")).toBeInTheDocument();
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
    finish(
      reply({
        ...proposed,
        status: "approved",
        events: [
          {
            action: "approve",
            reviewer_id: "supervisor-1",
            occurred_at: "2026-09-17T12:00:00Z",
            rationale: null,
          },
        ],
      }),
    );
    expect(await screen.findByText("READY FOR INTERVENTION REVIEW")).toBeInTheDocument();
    expect(screen.getByText("HUMAN VALIDATED")).toBeInTheDocument();
    expect(screen.getByText("ACCEPTED BY REVIEWER")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Working diagnosis" })).toBeInTheDocument();
    expect(screen.getByText(/training has not yet been selected/)).toBeInTheDocument();
    expect(mock).toHaveBeenCalledWith(
      expect.stringContaining("/approve"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("rejects through the API and never marks a rejection ready", async () => {
    route([proposed], async () =>
      reply({
        ...proposed,
        status: "rejected",
        events: [
          {
            action: "reject",
            reviewer_id: "qa-1",
            occurred_at: "2026-09-17T12:00:00Z",
            rationale: "Counterevidence",
          },
        ],
      }),
    );
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.type(
      screen.getByPlaceholderText("Your reviewer ID"),
      "qa-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    await userEvent.type(
      screen.getByLabelText("Reason for rejection"),
      "Counterevidence",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Confirm rejection" }),
    );
    expect(await screen.findByText("Diagnosis rejected")).toBeInTheDocument();
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
  });

  it("preserves the original proposal and requires separate approval after revision", async () => {
    const revision = {
      ...proposed.provider_hypothesis,
      cause_domain: "process_gap",
      explanation: "Reviewer found a process issue.",
    };
    const mock = route([proposed], async (path, init) => {
      expect(path.endsWith("/revise")).toBe(true);
      expect(JSON.parse(String(init?.body)).revision.cause_domain).toBe(
        "process_gap",
      );
      expect(Object.keys(JSON.parse(String(init?.body)).revision).sort()).toEqual([
        "cause_domain", "conflicting_evidence", "explanation", "missing_evidence",
        "observed_behavioral_defect", "performance_dimension", "supporting_evidence",
      ]);
      return reply({
        ...proposed,
        status: "revised",
        human_revision: revision,
        events: [
          {
            action: "revise",
            reviewer_id: "qa-1",
            occurred_at: "2026-09-17T12:00:00Z",
            rationale: "Process evidence",
          },
        ],
      });
    });
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.type(
      screen.getByPlaceholderText("Your reviewer ID"),
      "qa-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    fireEvent.change(screen.getByLabelText("Corrected cause"), {
      target: { value: "process_gap" },
    });
    fireEvent.change(screen.getByLabelText("Corrected explanation"), {
      target: { value: "Reviewer found a process issue." },
    });
    await userEvent.type(
      screen.getByLabelText("Reason for revision"),
      "Process evidence",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save revision" }),
    );
    expect(await screen.findByText("Reviewer correction")).toBeInTheDocument();
    expect(
      screen.getByText("Provider proposed a skill gap."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Reviewer found a process issue."),
    ).toBeInTheDocument();
    expect(screen.getByText("REVISED · NOT YET VALIDATED")).toBeInTheDocument();
    expect(screen.getByText(/PENDING APPROVAL/)).toBeInTheDocument();
    expect(screen.queryByText("HUMAN VALIDATED")).not.toBeInTheDocument();
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Approve human revision" }),
    ).toBeInTheDocument();
    expect(mock).toHaveBeenCalledWith(
      expect.stringContaining("/revise"),
      expect.anything(),
    );
  });

  it("keeps proposed state on mutation failure and surfaces provider failures safely", async () => {
    route([proposed], async () =>
      reply(
        {
          detail: {
            code: "invalid_state_transition",
            message: "Internal secret",
          },
        },
        409,
      ),
    );
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.type(
      screen.getByPlaceholderText("Your reviewer ID"),
      "qa-1",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Approve diagnosis" }),
    );
    await screen.findByRole("alert");
    expect(screen.getByText("NOT YET VALIDATED")).toBeInTheDocument();
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByText("Internal secret")).not.toBeInTheDocument();
  });

  it("handles no signals, no hypothesis, and backend unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) =>
        path.endsWith("/signals") ? reply([]) : reply([]),
      ),
    );
    const { unmount } = render(<ReviewWorkspace />);
    expect(
      await screen.findByText("No QA signals are available."),
    ).toBeInTheDocument();
    unmount();
    route([]);
    render(<ReviewWorkspace />);
    expect(
      await screen.findByText("No hypothesis for this signal yet."),
    ).toBeInTheDocument();
  });

  it("changes the observed workspace when a different signal is selected", async () => {
    const second = {
      ...signal,
      signal_id: "sig_2",
      criterion: "Follow-up documented",
      fail_count: 0,
      pass_count: 2,
      fail_rate: "0",
      feedback_count: 0,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) => {
        if (path.endsWith("/signals")) return reply([signal, second]);
        if (path.endsWith("/sig_2/review-evidence"))
          return reply({ signal: second, items: [] });
        if (path.endsWith("/sig_2/hypotheses")) return reply([]);
        if (path.endsWith("/review-evidence")) return reply(evidence);
        return reply([proposed]);
      }),
    );
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.click(
      screen.getByRole("button", { name: /Follow-up documented/ }),
    );
    expect(
      await screen.findByText("No hypothesis for this signal yet."),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("region", { name: "Diagnostic review" }),
      ).getByRole("heading", { name: "Follow-up documented" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("0.0%").length).toBeGreaterThan(0);
    expect(
      screen.queryByText("Provider proposed a skill gap."),
    ).not.toBeInTheDocument();
  });

  it("keeps the empty review state when provider output is rejected", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    route([], async () => pending);
    render(<ReviewWorkspace />);
    await screen.findByText("No hypothesis for this signal yet.");
    await userEvent.click(
      screen.getByRole("button", { name: "Request diagnostic hypothesis" }),
    );
    expect(screen.getByText("Generating hypothesis…")).toBeInTheDocument();
    finish(
      reply(
        {
          detail: {
            code: "invalid_provider_output",
            message: "Private feedback",
          },
        },
        502,
      ),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid hypothesis",
    );
    expect(
      screen.getByText("No hypothesis for this signal yet."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Private feedback")).not.toBeInTheDocument();
  });

  it("fails explicitly in real mode when no reasoning provider exists", async () => {
    // M5.6 real ResultsCX mode installs UnavailableReasoner: a request must not produce a
    // hypothesis, a local cause, or a design path, and must not fall back to a fixture.
    const mock = route([], async () =>
      reply(
        { detail: { code: "reasoner_unavailable", message: "internal detail" } },
        503,
      ),
    );
    render(<ReviewWorkspace />);
    await screen.findByText("No hypothesis for this signal yet.");
    expect(screen.getByText("Not requested")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Request diagnostic hypothesis" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No reasoning provider is configured",
    );
    expect(screen.queryByText("internal detail")).not.toBeInTheDocument();
    expect(screen.getByText("No hypothesis for this signal yet.")).toBeInTheDocument();
    expect(screen.getByText("Not requested")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.queryByText(/DIAGNOSTIC HYPOTHESIS$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/CONTROLLED DEMO/)).not.toBeInTheDocument();
    for (const cause of ["Skill Gap", "Knowledge Gap", "Process Gap"])
      expect(screen.queryByText(cause)).not.toBeInTheDocument();
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
    expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(mock.mock.calls.some(([path]) => String(path).includes("/api/designs/"))).toBe(false);
    // The deterministic observation is untouched by the failure.
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
  });

  it("shows an unavailable backend without making up signals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("private network detail");
      }),
    );
    render(<ReviewWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The diagnostic service is unavailable",
    );
    expect(
      screen.getByText("No QA signals are available."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("private network detail"),
    ).not.toBeInTheDocument();
  });

  it("renders the backend cause value without a failure-rate heuristic", async () => {
    const undetermined = {
      ...proposed,
      provider_hypothesis: {
        ...proposed.provider_hypothesis,
        cause_domain: "undetermined",
        performance_dimension: "undetermined",
      },
    };
    route([undetermined]);
    render(<ReviewWorkspace />);
    await loaded();
    expect(screen.getAllByText("Undetermined").length).toBeGreaterThan(0);
    expect(screen.queryByText("Skill Gap")).not.toBeInTheDocument();
  });

  it("identifies a controlled fixture as non-AI", async () => {
    const demo = {
      ...proposed,
      provider_hypothesis: {
        ...proposed.provider_hypothesis,
        provider_metadata: { provider: "m4-demo-fixture", model: null },
      },
    };
    route([demo]);
    render(<ReviewWorkspace />);
    await loaded();
    expect(
      screen.getByText(/CONTROLLED DEMO · DIAGNOSTIC HYPOTHESIS/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/The fixture performs no AI inference/),
    ).toBeInTheDocument();
    expect(screen.getByText("Fixture confidence value")).toBeInTheDocument();
    expect(
      screen.queryByText("Model-reported confidence"),
    ).not.toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Your reviewer ID"), "qa-1");
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    expect(screen.getByText(/original non-AI fixture proposal remains/)).toBeInTheDocument();
  });
});

describe("adversarial review states", () => {
  const second: Signal = {
    ...signal,
    signal_id: "sig_2",
    criterion: "Follow-up documented",
    fail_count: 0,
    pass_count: 2,
    fail_rate: "0",
    feedback_count: 0,
  };

  it("drops a hypothesis created for a signal the reviewer has since left", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "POST") return pending;
        if (path.endsWith("/signals")) return reply([signal, second]);
        if (path.endsWith("/review-evidence"))
          return reply(
            path.includes("sig_2") ? { signal: second, items: [] } : evidence,
          );
        return reply([]);
      }),
    );
    render(<ReviewWorkspace />);
    await screen.findByText("No hypothesis for this signal yet.");
    await userEvent.click(
      screen.getByRole("button", { name: "Request diagnostic hypothesis" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Follow-up documented/ }),
    );
    await screen.findByRole("heading", { name: "Follow-up documented" });
    finish(reply(proposed)); // Belongs to sig_1, resolved while sig_2 is open.
    await screen.findByRole("button", {
      name: "Request diagnostic hypothesis",
    });
    expect(
      screen.queryByText("Provider proposed a skill gap."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Skill Gap")).not.toBeInTheDocument();
  });

  it("sends a single approval for a double click", async () => {
    let finish!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    const mock = route([proposed], async () => pending);
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.type(
      screen.getByPlaceholderText("Your reviewer ID"),
      "qa-1",
    );
    const approve = screen.getByRole("button", { name: "Approve diagnosis" });
    await userEvent.dblClick(approve);
    fireEvent.click(approve);
    finish(reply({ ...proposed, status: "approved" }));
    await screen.findByText("HUMAN VALIDATED");
    const posts = mock.mock.calls.filter(
      ([, init]) => (init as RequestInit | undefined)?.method === "POST",
    );
    expect(posts).toHaveLength(1);
  });

  it("submits multi-line missing evidence from the revision form verbatim", async () => {
    const mock = route([proposed], async (path, init) => {
      const body = JSON.parse(String(init?.body));
      expect(path.endsWith("/revise")).toBe(true);
      expect(body.revision.missing_evidence).toEqual([
        "Observe a live call",
        "Second open question",
      ]);
      return reply({
        ...proposed,
        status: "revised",
        human_revision: { ...proposed.provider_hypothesis, ...body.revision },
      });
    });
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.type(
      screen.getByPlaceholderText("Your reviewer ID"),
      "qa-1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Revise" }));
    await userEvent.type(
      screen.getByLabelText(/Missing evidence \/ unanswered questions/),
      "{End}{Enter}Second open question",
    );
    await userEvent.type(
      screen.getByLabelText("Reason for revision"),
      "More questions",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Save revision" }),
    );
    await screen.findByText("Reviewer correction");
    expect(screen.getByText("Second open question")).toBeInTheDocument();
    expect(mock).toHaveBeenCalledWith(
      expect.stringContaining("/revise"),
      expect.anything(),
    );
  });

  it("marks an approved revision validated without re-labelling the AI proposal", async () => {
    route([
      {
        ...proposed,
        status: "revised",
        revision_approved: true,
        human_revision: {
          ...proposed.provider_hypothesis,
          cause_domain: "process_gap",
          performance_dimension: "undetermined",
          explanation: "Reviewer found a process issue.",
        },
        events: [
          {
            action: "revise",
            reviewer_id: "qa-1",
            occurred_at: "2026-09-17T12:00:00Z",
            rationale: "Process evidence",
          },
          {
            action: "approve",
            reviewer_id: "lead-1",
            occurred_at: "2026-09-17T12:05:00Z",
            rationale: null,
          },
        ],
      },
    ]);
    render(<ReviewWorkspace />);
    await loaded();
    expect(
      screen.getByText("SUPERSEDED"),
    ).toBeInTheDocument();
    expect(screen.getByText("HUMAN VALIDATED")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Working diagnosis",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Process Gap · Undetermined")).toBeInTheDocument();
    expect(screen.getByText("Human-revised working diagnosis")).toBeInTheDocument();
    expect(screen.getByText("READY FOR INTERVENTION REVIEW")).toBeInTheDocument();
    expect(screen.getByText("Revision approved")).toBeInTheDocument();
  });

  it("refuses malformed records instead of rendering them as validated", async () => {
    route([
      {
        ...proposed,
        status: "approved",
        provider_hypothesis: { hypothesis_id: "hyp_1" },
      } as unknown as RecordState,
    ]);
    render(<ReviewWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected response",
    );
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByText("HUMAN VALIDATED")).not.toBeInTheDocument();
  });

  it("does not validate on an unknown status value", async () => {
    route([{ ...proposed, status: "validated" } as unknown as RecordState]);
    render(<ReviewWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected response",
    );
    expect(screen.queryByText("READY FOR INTERVENTION REVIEW")).not.toBeInTheDocument();
  });

  it("names a citation that is outside this signal's evidence instead of showing nothing", async () => {
    const foreign: RecordState = {
      ...proposed,
      provider_hypothesis: {
        ...proposed.provider_hypothesis,
        supporting_evidence: [{ item_id: "ev_other_signal", evaluation_id: "eval_9" }],
      },
    };
    route([foreign]);
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.click(screen.getByRole("button", { name: /Evaluation eval_9/ }));
    expect(screen.getByText("Citation not in this signal’s evidence")).toBeInTheDocument();
    expect(screen.queryByText("synthetic.xlsx · QA · 2")).not.toBeInTheDocument();
    expect(screen.queryByText("Next step unclear")).not.toBeInTheDocument();
  });

  it("shows source answer and deterministic result as separate pipeline fields", async () => {
    route();
    render(<ReviewWorkspace />);
    await loaded();
    await userEvent.click(
      within(
        screen.getByRole("complementary", { name: "Evidence inspector" }),
      ).getByRole("button", { name: /Evaluation eval_2/ }),
    );
    expect(screen.getByText("Yes · Pass")).toBeInTheDocument();
    expect(screen.getByText("Source answer / result")).toBeInTheDocument();
  });
});

describe("M5 orchestration in the review workspace", () => {
  const approved = { ...proposed, status: "approved" as const };

  it("requires approval before exposing design action", async () => {
    route();
    render(<ReviewWorkspace />);
    await loaded();
    expect(screen.queryByRole("button", { name: "DESIGN INTERVENTION" })).not.toBeInTheDocument();
  });

  it("shows truthful loading and creates one training run despite repeated clicks", async () => {
    let complete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { complete = resolve; });
    const mock = vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/signals")) return reply([signal]);
      if (path.endsWith("/review-evidence")) return reply(evidence);
      if (path.endsWith("/hypotheses")) return reply([approved]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/api/designs/") && init?.method === "POST") return pending;
      if (path.includes("/api/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      if (path.includes("/api/interventions/")) return reply(interventionFixture());
      throw new Error(path);
    });
    vi.stubGlobal("fetch", mock);
    render(<ReviewWorkspace />);
    const button = await screen.findByRole("button", { name: "DESIGN INTERVENTION" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.getByRole("status")).toHaveTextContent("Designing intervention and learning experience");
    complete(reply(designFixture()));
    expect(await screen.findByText("READY FOR ALIGNMENT REVIEW")).toBeInTheDocument();
    expect(screen.getByText("Proposed activities")).toBeInTheDocument();
    expect(screen.getByText("Hands-on practice")).toBeInTheDocument();
    expect(screen.getByText("Practice rubric")).toBeInTheDocument();
    expect(screen.queryByText("VALIDATED TRAINING")).not.toBeInTheDocument();
    expect(mock.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  });

  it("drops a design that finishes after the reviewer switched to another hypothesis", async () => {
    const other: RecordState = { ...approved, provider_hypothesis: { ...approved.provider_hypothesis, hypothesis_id: "hyp_2", explanation: "Second proposal." } };
    let complete!: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { complete = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/signals")) return reply([signal]);
      if (path.endsWith("/review-evidence")) return reply(evidence);
      if (path.endsWith("/hypotheses")) return reply([approved, other]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/api/designs/") && init?.method === "POST") return pending;
      if (path.includes("/api/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      if (path.includes("/api/interventions/")) return reply(interventionFixture());
      throw new Error(path);
    }));
    render(<ReviewWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: "DESIGN INTERVENTION" }));
    fireEvent.change(screen.getByLabelText("Review history"), { target: { value: "hyp_2" } });
    expect(await screen.findByText("Second proposal.")).toBeInTheDocument();
    complete(reply(designFixture()));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("READY FOR ALIGNMENT REVIEW")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not manufacture a design on failed or malformed API output", async () => {
    let response: unknown = { detail: { code: "invalid_design_output", message: "private" } };
    let status = 502;
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/signals")) return reply([signal]);
      if (path.endsWith("/review-evidence")) return reply(evidence);
      if (path.endsWith("/hypotheses")) return reply([approved]);
      if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
      if (path.includes("/api/designs/") && init?.method === "POST") return reply(response, status);
      if (path.includes("/api/designs/")) return reply({ detail: { code: "design_not_found" } }, 404);
      if (path.includes("/api/interventions/")) return reply(interventionFixture());
      throw new Error(path);
    }));
    render(<ReviewWorkspace />);
    await userEvent.click(await screen.findByRole("button", { name: "DESIGN INTERVENTION" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid output");
    expect(screen.queryByText("READY FOR ALIGNMENT REVIEW")).not.toBeInTheDocument();
    response = { ...designFixture(), training_design: { target_behaviors: null } };
    status = 200;
    await userEvent.click(screen.getByRole("button", { name: "DESIGN INTERVENTION" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected response");
    expect(screen.queryByText("READY FOR ALIGNMENT REVIEW")).not.toBeInTheDocument();
  });
});
