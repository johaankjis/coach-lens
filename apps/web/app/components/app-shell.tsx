"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { NAV_SECTIONS } from "../../lib/navigation";

/** Line icons for the primary navigation, keyed by route. Decorative only; labels carry meaning. */
const NAV_ICONS: Record<string, ReactNode> = {
  "/": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3.5 11 12 4l8.5 7" />
      <path d="M6 9.5V20h12V9.5" />
      <path d="M10 20v-6h4v6" />
    </svg>
  ),
  "/agent-insights": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 19c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
      <circle cx="17" cy="9" r="2.5" />
      <path d="M16 13.5c3 0 5.5 2 5.5 5" />
    </svg>
  ),
  "/training": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 5.5h6.5a2.5 2.5 0 0 1 2.5 2.5v11a2 2 0 0 0-2-2H3z" />
      <path d="M21 5.5h-6.5A2.5 2.5 0 0 0 12 8v11a2 2 0 0 1 2-2h7z" />
    </svg>
  ),
  "/role-play": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 13a8 8 0 0 1 16 0" />
      <rect x="3" y="13" width="4" height="6" rx="1.5" />
      <rect x="17" y="13" width="4" height="6" rx="1.5" />
      <path d="M19 19v1a2 2 0 0 1-2 2h-3" />
    </svg>
  ),
  "/kpi-tracker": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 19V13" />
      <path d="M12 19V8" />
      <path d="M19 19V4" />
      <path d="M3 19h18" />
    </svg>
  ),
  "/reports": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6" />
      <path d="M9 16h6" />
    </svg>
  ),
  "/resources": (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4l2 2h9A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" />
    </svg>
  ),
};

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
            <svg viewBox="0 0 24 24">
              <path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z" />
              <path d="M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z" />
            </svg>
          </span>
          <div>
            <strong>
              Coach<em>Lens</em>
            </strong>
            <span>From Insights to Impact</span>
          </div>
        </Link>
        <div className="topbar-scope" aria-hidden="true">
          Evidence-driven QA diagnosis · AI proposes and reviews · humans validate
        </div>
        <div className="topbar-right">
          <span className="workspace-label">RESULTSCX · AI OPERATIONS WORKSPACE</span>
          <div className="user-chip" role="note" aria-label="Current role">
            <span className="avatar" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="8.5" r="4" />
                <path d="M4.5 20c0-4 3.4-6.5 7.5-6.5s7.5 2.5 7.5 6.5" />
              </svg>
            </span>
            <span>
              <strong>Supervisor</strong>
              <small>Reviewer ID entered per decision</small>
            </span>
          </div>
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
                    title={section.role}
                  >
                    <span className="sidebar-icon">{NAV_ICONS[section.href]}</span>
                    <span className="sidebar-label">{section.label}</span>
                    {section.status === "planned" && <span className="sidebar-status">Planned</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="sidebar-foot">
            <strong>CoachLens</strong>
            <span>ResultsCX · Powered by AWS</span>
            <span>Home summarizes. Agent Insights explains. Training and Role-Play display what was generated.</span>
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
