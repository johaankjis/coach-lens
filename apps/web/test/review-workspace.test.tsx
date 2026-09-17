import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReviewWorkspace from "../app/review-workspace";
import type { EvidenceBundle, RecordState, Signal } from "../lib/diagnostics";

const signal: Signal = {
  signal_id: "sig_1",
  domain: "member_experience",
  criterion: "Resolution clarity",
  evaluated_results: 2,
  evaluated_evaluations: 2,
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
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
async function loaded() {
  await screen.findByText("Provider proposed a skill gap.");
}
beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("diagnostic review semantics", () => {
  it("labels deterministic observations and an unvalidated proposal, without probability language", async () => {
    route();
    render(<ReviewWorkspace />);
    await loaded();
    expect(
      screen.getByText(/OBSERVED · DETERMINISTIC QA SIGNAL/),
    ).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getAllByText("50.0%").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/AI-GENERATED · DIAGNOSTIC HYPOTHESIS/),
    ).toBeInTheDocument();
    expect(screen.getByText("NOT YET VALIDATED")).toBeInTheDocument();
    expect(screen.getByText("0.78")).toBeInTheDocument();
    expect(
      screen.getByText(/not a statistically calibrated probability/),
    ).toBeInTheDocument();
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
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
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
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
    expect(await screen.findByText("READY FOR DESIGN")).toBeInTheDocument();
    expect(screen.getByText("HUMAN VALIDATED")).toBeInTheDocument();
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
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
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
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
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
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
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
      screen.getByText("SUPERSEDED · REVISION VALIDATED"),
    ).toBeInTheDocument();
    expect(screen.queryByText("HUMAN VALIDATED")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        name: "Validated diagnosis · human revision",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Process Gap · Undetermined")).toBeInTheDocument();
    expect(screen.getByText("READY FOR DESIGN")).toBeInTheDocument();
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
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
    expect(screen.queryByText("HUMAN VALIDATED")).not.toBeInTheDocument();
  });

  it("does not validate on an unknown status value", async () => {
    route([{ ...proposed, status: "validated" } as unknown as RecordState]);
    render(<ReviewWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "unexpected response",
    );
    expect(screen.queryByText("READY FOR DESIGN")).not.toBeInTheDocument();
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
