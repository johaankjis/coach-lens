import { shortId, type EvidenceReference } from "../lib/diagnostics";

export function EvidenceLink({
  reference,
  relationName,
  onSelect,
}: {
  reference: EvidenceReference;
  relationName: string;
  onSelect: (reference: EvidenceReference) => void;
}) {
  return (
    <button
      type="button"
      className="evidence-link"
      onClick={() => onSelect(reference)}
    >
      <span>
        {reference.item_id === "signal"
          ? "Aggregate QA signal"
          : `Evaluation ${shortId(reference.evaluation_id ?? "")}`}
      </span>
      <span className="evidence-link-meta">
        {relationName} <span aria-hidden="true">↗</span>
      </span>
    </button>
  );
}

export function EvidenceGroup({
  title,
  references,
  kind,
  onSelect,
  emptyText = "None cited in this diagnosis.",
}: {
  title: string;
  references: EvidenceReference[];
  kind: string;
  onSelect: (reference: EvidenceReference) => void;
  emptyText?: string;
}) {
  return (
    <section className={`evidence-group ${kind}`} aria-label={title}>
      <div className="evidence-group-heading">
        <h4>{title}</h4>
        <span>{references.length}</span>
      </div>
      {references.length ? (
        <div className="evidence-links">
          {references.map((reference) => (
            <EvidenceLink
              key={reference.item_id}
              reference={reference}
              relationName={kind}
              onSelect={onSelect}
            />
          ))}
        </div>
      ) : (
        <p className="quiet">{emptyText}</p>
      )}
    </section>
  );
}
