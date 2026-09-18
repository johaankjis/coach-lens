import Link from "next/link";
import { AGENT_INSIGHTS_PATH } from "../../lib/home/read-model";
import { sectionFor } from "../../lib/navigation";

/**
 * Restrained "planned" route. It names the section's role and data source, and routes back
 * to the parts of the product that exist. It deliberately has no fake controls or numbers.
 */
export default function SectionPlaceholder({
  href,
  summary,
  dependsOn,
}: {
  href: string;
  summary: string;
  dependsOn: string[];
}) {
  const section = sectionFor(href);
  if (!section) throw new Error(`Unknown section ${href}`);
  return (
    <main className="workspace placeholder" aria-labelledby="section-title">
      <span className="eyebrow">Planned section · {section.source}</span>
      <h1 id="section-title">{section.label}</h1>
      <p className="placeholder-role">{section.role}</p>
      <p>{summary}</p>
      <section className="placeholder-card" aria-label="What this section will show">
        <h2>Opens when these land</h2>
        <ul>
          {dependsOn.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="quiet">
          Until then this page shows nothing, rather than placeholder figures that could be read
          as ResultsCX results.
        </p>
      </section>
      <div className="placeholder-actions">
        <Link className="button primary" href="/">
          Back to Home
        </Link>
        <Link className="button secondary" href={AGENT_INSIGHTS_PATH}>
          Open Agent Insights
        </Link>
      </div>
    </main>
  );
}
