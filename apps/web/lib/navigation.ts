/**
 * Product navigation. Home, Agent Insights, Training, and Role-Play read real backend state.
 * KPI Tracker shows measurement status over the observed baseline. Reports and Resources are
 * restrained planned pages that name the lane that will fill them.
 */
export type NavSection = {
  href: string;
  label: string;
  /** One-line role of the section in the product. */
  role: string;
  status: "live" | "planned";
  /** Which milestone / lane supplies the section's data. */
  source: string;
};

export const NAV_SECTIONS: NavSection[] = [
  { href: "/", label: "Home", role: "Command center", status: "live", source: "M2 · M3 · AWS-3 · AWS-4 · AWS-5" },
  {
    href: "/agent-insights",
    label: "Agent Insights",
    role: "Deep diagnostic workspace",
    status: "live",
    source: "M3 · M4 · AWS-3 · AWS-4 · AWS-5",
  },
  {
    href: "/training",
    label: "Training",
    role: "Generated training package",
    status: "live",
    source: "AWS-4 · AWS-5",
  },
  {
    href: "/role-play",
    label: "Role-Play",
    role: "Hands-on practice script",
    status: "live",
    source: "AWS-5 practice scenarios",
  },
  {
    href: "/kpi-tracker",
    label: "KPI Tracker",
    role: "Outcome measurement",
    status: "planned",
    source: "Outcome evaluation",
  },
  { href: "/reports", label: "Reports", role: "Impact reporting", status: "planned", source: "Outcome evaluation" },
  {
    href: "/resources",
    label: "Resources",
    role: "Methodology and evidence policy",
    status: "planned",
    source: "Documentation",
  },
];

export const sectionFor = (href: string) => NAV_SECTIONS.find((section) => section.href === href);
