"use client";

import { useState } from "react";
import { label, shortId, type Diagnosis, type EvidenceBundle, type EvidenceReference } from "../lib/diagnostics";

/**
 * The M4 human revision form. Agent Insights and Home render the same component so a
 * revision recorded from either page carries the exact `POST /hypotheses/{id}/revise` contract:
 * `reviewer_id`, `rationale`, and a seven-field `revision` diagnosis. Nothing here mutates;
 * the owning page submits.
 */
export const refKey = (reference: EvidenceReference) => reference.item_id;

export function relation(
  reference: EvidenceReference,
  record: Diagnosis | null,
): "supporting" | "conflicting" | "uncited" {
  if (
    record?.supporting_evidence.some(
      (item) => refKey(item) === refKey(reference),
    )
  )
    return "supporting";
  if (
    record?.conflicting_evidence.some(
      (item) => refKey(item) === refKey(reference),
    )
  )
    return "conflicting";
  return "uncited";
}

export function RevisionForm({
  original,
  bundle,
  reviewer,
  onCancel,
  onSubmit,
  busy,
  demo,
}: {
  original: Diagnosis;
  bundle: EvidenceBundle | null;
  reviewer: string;
  onCancel: () => void;
  onSubmit: (revision: Diagnosis, rationale: string) => void;
  busy: boolean;
  demo: boolean;
}) {
  const [draft, setDraft] = useState<Diagnosis>(() => ({
    observed_behavioral_defect: original.observed_behavioral_defect,
    cause_domain: original.cause_domain,
    performance_dimension: original.performance_dimension,
    explanation: original.explanation,
    supporting_evidence: [...original.supporting_evidence],
    conflicting_evidence: [...original.conflicting_evidence],
    missing_evidence: [...original.missing_evidence],
  }));
  const [rationale, setRationale] = useState("");
  // Keep the textarea text verbatim while typing; it is split into list items on submit so
  // newlines and spaces are not swallowed mid-edit.
  const [missingText, setMissingText] = useState(() =>
    original.missing_evidence.join("\n"),
  );
  const missingEvidence = missingText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const update = <K extends keyof Diagnosis>(field: K, value: Diagnosis[K]) =>
    setDraft((current) => ({ ...current, [field]: value }));
  const allReferences: EvidenceReference[] = [
    { item_id: "signal", evaluation_id: null },
    ...(bundle?.items.map((item) => ({
      item_id: item.item_id,
      evaluation_id: item.evaluation_id,
    })) ?? []),
  ];
  const setRelation = (reference: EvidenceReference, next: string) =>
    setDraft((current) => ({
      ...current,
      supporting_evidence: [
        ...current.supporting_evidence.filter(
          (item) => item.item_id !== reference.item_id,
        ),
        ...(next === "supporting" ? [reference] : []),
      ],
      conflicting_evidence: [
        ...current.conflicting_evidence.filter(
          (item) => item.item_id !== reference.item_id,
        ),
        ...(next === "conflicting" ? [reference] : []),
      ],
    }));
  return (
    <form
      className="revision-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({ ...draft, missing_evidence: missingEvidence }, rationale);
      }}
    >
      <div className="section-title">
        <span className="eyebrow">Human correction</span>
        <h3>Revise diagnosis</h3>
        <p>
          The original {demo ? "non-AI fixture" : "AI"} proposal remains in the record. This revision will
          need a separate approval.
        </p>
      </div>
      <label>
        Observed behavioral defect{" "}
        <textarea
          required
          value={draft.observed_behavioral_defect}
          onChange={(event) =>
            update("observed_behavioral_defect", event.target.value)
          }
        />
      </label>
      <div className="form-grid">
        <label>
          Corrected cause{" "}
          <select
            value={draft.cause_domain}
            onChange={(event) => update("cause_domain", event.target.value)}
          >
            {["knowledge_gap", "skill_gap", "process_gap", "undetermined"].map(
              (value) => (
                <option key={value} value={value}>
                  {label(value)}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          Corrected dimension{" "}
          <select
            value={draft.performance_dimension}
            onChange={(event) =>
              update("performance_dimension", event.target.value)
            }
          >
            {["capability", "execution", "undetermined"].map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label>
        Corrected explanation{" "}
        <textarea
          required
          value={draft.explanation}
          onChange={(event) => update("explanation", event.target.value)}
        />
      </label>
      <fieldset>
        <legend>Evidence relationships</legend>
        <p className="quiet">
          Keep at least one supporting reference. The backend validates every
          citation.
        </p>
        <div className="revision-evidence">
          {allReferences.map((reference) => (
            <label key={reference.item_id}>
              <span>
                {reference.item_id === "signal"
                  ? "Aggregate QA signal"
                  : `Evaluation ${shortId(reference.evaluation_id ?? "")}`}
              </span>
              <select
                aria-label={`Evidence relationship for ${reference.item_id}`}
                value={relation(reference, draft)}
                onChange={(event) => setRelation(reference, event.target.value)}
              >
                <option value="uncited">Uncited</option>
                <option value="supporting">Supporting</option>
                <option value="conflicting">Conflicting</option>
              </select>
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        Missing evidence / unanswered questions{" "}
        <textarea
          value={missingText}
          onChange={(event) => setMissingText(event.target.value)}
        />
        <span className="input-help">
          One item per line. Required if cause is Undetermined.
        </span>
      </label>
      <label>
        Reason for revision{" "}
        <textarea
          required
          value={rationale}
          onChange={(event) => setRationale(event.target.value)}
        />
      </label>
      <div className="form-actions">
        <button type="button" className="button secondary" onClick={onCancel}>
          Cancel
        </button>
        <button
          className="button primary"
          disabled={
            busy ||
            !reviewer.trim() ||
            !draft.supporting_evidence.length ||
            (draft.cause_domain === "undetermined" && !missingEvidence.length)
          }
        >
          Save revision
        </button>
      </div>
    </form>
  );
}

