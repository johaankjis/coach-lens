"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { NAV_SECTIONS } from "../../lib/navigation";

/**
 * Product shell: brand bar, primary sidebar navigation, and the routed content area.
 * The review workspace and Home both render inside it, so chrome lives here only.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "/";
  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="topbar">
        <Link href="/" className="brand" aria-label="CoachLens AI home">
          <span className="brand-mark" aria-hidden="true">
            C<span>●</span>
          </span>
          <div>
            <strong>
              CoachLens <em>AI</em>
            </strong>
            <span>Evidence-Driven Performance Diagnosis</span>
          </div>
        </Link>
        <div className="topbar-right">
          <span className="workspace-label">RESULTSCX · AI OPERATIONS WORKSPACE</span>
          <span className="milestone">COMMAND CENTER · AWS-1 → AWS-5</span>
        </div>
      </header>
      <div className="shell-body">
        <nav className="sidebar" aria-label="Primary">
          <ul className="sidebar-list">
            {NAV_SECTIONS.map((section) => {
              const active = isActive(section.href);
              return (
                <li key={section.href}>
                  <Link
                    href={section.href}
                    className={`sidebar-link ${active ? "active" : ""} ${section.status}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <span className="sidebar-label">{section.label}</span>
                    <span className="sidebar-role">{section.role}</span>
                    {section.status === "planned" && (
                      <span className="sidebar-status">Planned</span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="sidebar-foot">
            Home summarizes. Agent Insights explains. Training and Role-Play display what was
            generated. Outcome measurement is pending.
          </div>
        </nav>
        <div id="main-content" className="shell-content" tabIndex={-1}>
          {children}
        </div>
      </div>
      <footer className="footer">
        CoachLens AI · ResultsCX x AWS{" "}
        <span>
          Deterministic code owns counts. AI proposes and reviews. Humans validate before any
          intervention.
        </span>
      </footer>
    </div>
  );
}
