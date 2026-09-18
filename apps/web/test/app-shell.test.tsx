import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AppShell from "../app/components/app-shell";
import ReportsPage from "../app/reports/page";
import { NAV_SECTIONS } from "../lib/navigation";

const pathname = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

describe("Product shell", () => {
  it("lists every product section with Home, Agent Insights, Training, and Role-Play live", () => {
    pathname.current = "/";
    render(<AppShell><p>content</p></AppShell>);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual(NAV_SECTIONS.map((section) => section.href));
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/", "/agent-insights", "/training", "/role-play", "/kpi-tracker", "/reports", "/resources"]);
    expect(within(nav).getAllByText("Planned")).toHaveLength(3);
    expect(within(nav).getByRole("link", { name: /Training/ })).not.toHaveTextContent("Planned");
    expect(within(nav).getByRole("link", { name: /Role-Play/ })).not.toHaveTextContent("Planned");
    expect(within(nav).getByRole("link", { name: /Home/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /Agent Insights/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main-content");
    expect(document.getElementById("main-content")).toHaveAttribute("tabindex", "-1");
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("marks the current section active on its route, including a query-string deep link", () => {
    pathname.current = "/agent-insights";
    const view = render(<AppShell><p>content</p></AppShell>);
    let nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: /Agent Insights/ })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: /Home/ })).not.toHaveAttribute("aria-current");
    view.unmount();
    pathname.current = "/training";
    render(<AppShell><p>content</p></AppShell>);
    nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: /Training/ })).toHaveAttribute("aria-current", "page");
  });

  it("renders a planned section without fake controls or figures", () => {
    render(<ReportsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Reports" })).toBeInTheDocument();
    expect(screen.getByText(/Planned section/)).toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Open Agent Insights" })).toHaveAttribute("href", "/agent-insights");
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
  });
});
