/**
 * Product navigation. Only Home and Agent Insights are implemented in UI-1; the remaining
 * sections route to restrained placeholder pages that name the milestone that will fill them.
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
  { href: "/", label: "Home", role: "Command center", status: "live", source: "M2 · M3 · AWS-3" },
  {
    href: "/agent-insights",
    label: "Agent Insights",
    role: "Deep diagnostic workspace",
    status: "live",
    source: "M3 · M4 · AWS-3 · M5",
  },
  {
    href: "/training",
    label: "Training",
    role: "Downstream intervention and training design",
    status: "planned",
    source: "AWS-4 · AWS-5",
  },
  {
    href: "/role-play",
    label: "Role-Play",
    role: "Practice simulation",
    status: "planned",
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
