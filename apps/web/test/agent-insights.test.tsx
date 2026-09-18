import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentInsightsPage from "../app/agent-insights/page";
import { awaiting, secondSignal, topSignal } from "./home.test-fixture";

function reply(value: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => value } as Response;
}
function route() {
  const mock = vi.fn(async (path: string) => {
    if (path.endsWith("/signals")) return reply([topSignal, secondSignal]);
    if (path.endsWith("/review-evidence")) return reply({ signal: path.includes("sig_second") ? secondSignal : topSignal, items: [] });
    if (path.endsWith("/sig_second/hypotheses")) return reply([]);
    if (path.endsWith("/sig_top/hypotheses")) return reply([awaiting]);
    if (path.endsWith("/evidence-validation")) return reply({ detail: { code: "validation_not_found" } }, 404);
    if (path.endsWith("/hypotheses")) return reply({ detail: { code: "signal_not_found" } }, 404);
    if (path.includes("/review-evidence")) return reply({ detail: { code: "signal_not_found" } }, 404);
    throw new Error(`Unexpected route ${path}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}
const page = async (params: Record<string, string | string[] | undefined>) =>
  render(await AgentInsightsPage({ searchParams: Promise.resolve(params) }));

describe("Agent Insights route", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens the existing three-column review workspace", async () => {
    route();
    await page({});
    expect(screen.getByRole("heading", { level: 1, name: "From QA evidence to a reviewed diagnosis." })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Observed QA signals" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Diagnostic review" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Evidence inspector" })).toBeInTheDocument();
    expect(await screen.findByText("Agents close calls without confirming the next step.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Resolution clarity/ })).toHaveAttribute("aria-current", "true");
  });

  it("preselects the signal Home linked to", async () => {
    const mock = route();
    await page({ signal: "sig_second" });
    expect(await screen.findByRole("heading", { level: 2, name: "HIPAA verification" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /HIPAA verification/ })).toHaveAttribute("aria-current", "true");
    expect(await screen.findByText("No hypothesis for this signal yet.")).toBeInTheDocument();
    expect(mock).toHaveBeenCalledWith(expect.stringContaining("/signals/sig_second/review-evidence"), expect.anything());
    expect(mock).not.toHaveBeenCalledWith(expect.stringContaining("/signals/sig_top/hypotheses"), expect.anything());
  });

  it("falls back to the backend's first signal when the requested one does not exist", async () => {
    route();
    await page({ signal: "sig_missing" });
    expect(await screen.findByText("Agents close calls without confirming the next step.")).toBeInTheDocument();
    expect(screen.queryByText("Evidence unavailable")).not.toBeInTheDocument();
  });
});
