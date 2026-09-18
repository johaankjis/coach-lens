"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import DesignWorkspace from "./design-workspace";
import { EvidenceGroup } from "./evidence-links";
import InterventionPanel from "./intervention-panel";
import { isAlignmentReview, isDesignResult, type AlignmentReview, type DesignResult } from "../lib/designs";
import { isInterventionRecord, type InterventionRecord } from "../lib/interventions";
import {
  api,
  ApiError,
  isEvidenceBundle,
  isEvidenceValidation,
  isRecordList,
  isRecordState,
  isSignalList,
  label,
  shortId,
  validated,
  type Diagnosis,
  type EvidenceBundle,
  type EvidenceValidation,
  type EvidenceItem,
  type EvidenceReference,
  type RecordState,
  type Signal,
} from "../lib/diagnostics";

const signalPath = (id: string) => `/signals/${encodeURIComponent(id)}`;
const hypothesisPath = (id: string) => `/hypotheses/${encodeURIComponent(id)}`;
const percent = (value: string) => `${(Number(value) * 100).toFixed(1)}%`;
const refKey = (reference: EvidenceReference) => reference.item_id;

function relation(
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

function DiagnosisBody({
  diagnosis,
  confidence,
  demo = false,
  human = false,
  onSelect,
}: {
  diagnosis: Diagnosis;
  confidence?: string;
  demo?: boolean;
  human?: boolean;
  onSelect: (reference: EvidenceReference) => void;
}) {
  return (
    <>
      <div className="diagnosis-fields">
        <div>
          <span className="field-label">
            {human ? "Corrected cause" : "Proposed cause"}
          </span>
          <strong>{label(diagnosis.cause_domain)}</strong>
        </div>
        <div>
          <span className="field-label">
            {human ? "Corrected dimension" : "Performance dimension"}
          </span>
          <strong>{label(diagnosis.performance_dimension)}</strong>
        </div>
      </div>
      <div className="reasoning">
        <span className="field-label">
          {human ? "Reviewer explanation" : "Reasoning / explanation"}
        </span>
        <p>{diagnosis.explanation}</p>
      </div>
      {confidence !== undefined && (
        <div className="confidence">
          <div>
            <span className="field-label">
              {demo ? "Fixture confidence value" : "Model-reported confidence"}
            </span>
            <strong>{confidence}</strong>
          </div>
          <p>
            {demo
              ? "Fixed synthetic fixture value. No model reported it."
              : "Provider self-report for this hypothesis."}{" "}
            It is not a statistically calibrated probability.
          </p>
        </div>
      )}
      <div className="evidence-pair">
        <EvidenceGroup
          title="Supporting evidence"
          references={diagnosis.supporting_evidence}
          kind="supporting"
          onSelect={onSelect}
        />
        <EvidenceGroup
          title="Conflicting evidence"
          references={diagnosis.conflicting_evidence}
          kind="conflicting"
          onSelect={onSelect}
        />
      </div>
      <div className="missing">
        <h4>Missing evidence / unanswered questions</h4>
        {diagnosis.missing_evidence.length ? (
          <ul>
            {diagnosis.missing_evidence.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        ) : (
          <p>None recorded by the reasoner.</p>
        )}
      </div>
    </>
  );
}

function RevisionForm({
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

export default function ReviewWorkspace() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [bundle, setBundle] = useState<EvidenceBundle | null>(null);
  const [records, setRecords] = useState<RecordState[]>([]);
  const [recordId, setRecordId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] =
    useState<EvidenceReference | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [rationale, setRationale] = useState("");
  const [action, setAction] = useState<"reject" | "revise" | null>(null);
  const [loadingSignals, setLoadingSignals] = useState(true);
  const [loadingSignal, setLoadingSignal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [signalError, setSignalError] = useState<string | null>(null);
  const [designResult, setDesignResult] = useState<DesignResult | null>(null);
  const [evidenceValidation, setEvidenceValidation] = useState<EvidenceValidation | null>(null);
  const [interventionRecord, setInterventionRecord] = useState<InterventionRecord | null>(null);
  const [designing, setDesigning] = useState(false);
  const [alignmentReview, setAlignmentReview] = useState<AlignmentReview | null>(null);
  const [checkingAlignment, setCheckingAlignment] = useState(false);
  const [interventionStep, setInterventionStep] = useState<"propose" | "validate" | null>(null);
  // Async results are applied only to the signal that was selected when the request started.
  const selectedRef = useRef<string | null>(null);
  const recordRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  useEffect(() => {
    selectedRef.current = selectedId;
  }, [selectedId]);
  useEffect(() => {
    recordRef.current = recordId;
  }, [recordId]);
  const selectedSignal =
    signals.find((signal) => signal.signal_id === selectedId) ?? null;
  const record =
    records.find(
      (entry) => entry.provider_hypothesis.hypothesis_id === recordId,
    ) ?? null;
  const isDemo =
    record?.provider_hypothesis.provider_metadata.provider ===
    "m4-demo-fixture";
  const currentDiagnosis =
    record?.human_revision ?? record?.provider_hypothesis ?? null;
  const currentValidation = evidenceValidation?.hypothesis_id === recordId ? evidenceValidation : null;
  const currentIntervention = interventionRecord?.hypothesis_id === recordId ? interventionRecord : null;
  const trainingGate = currentIntervention?.solution_validation ? currentIntervention.handoff.training_design_gate : null;
  const evidenceItem: EvidenceItem | undefined = bundle?.items.find(
    (item) => item.item_id === selectedEvidence?.item_id,
  );

  const loadSignals = useCallback(async () => {
    try {
      const result = await api("/signals", isSignalList);
      setSignals(result);
      setLoadingSignal(true);
      setSelectedId((current) =>
        result.some((signal) => signal.signal_id === current)
          ? current
          : (result[0]?.signal_id ?? null),
      );
    } catch (cause) {
      setError((cause as Error).message);
      setSignals([]);
      setSelectedId(null);
    } finally {
      setLoadingSignals(false);
    }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(loadSignals);
  }, [loadSignals]);
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    Promise.all([
      api(`${signalPath(selectedId)}/review-evidence`, isEvidenceBundle),
      api(`${signalPath(selectedId)}/hypotheses`, isRecordList),
    ])
      .then(([evidence, hypotheses]) => {
        if (cancelled) return;
        setBundle(evidence);
        setRecords(hypotheses);
        setRecordId(hypotheses[0]?.provider_hypothesis.hypothesis_id ?? null);
        setDesignResult(null);
        setAlignmentReview(null);
        setEvidenceValidation(null);
        setInterventionRecord(null);
      })
      .catch((cause) => {
        if (!cancelled) setSignalError((cause as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoadingSignal(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);
  useEffect(() => {
    // A stored semantic review belongs to one hypothesis; reload it when the selection changes
    // so a reviewer never sees a stale panel or an empty one for an already-reviewed proposal.
    if (!recordId) return;
    const id = recordId;
    let cancelled = false;
    api(`${hypothesisPath(id)}/evidence-validation`, isEvidenceValidation)
      .then((result) => { if (!cancelled && result.hypothesis_id === id) setEvidenceValidation(result); })
      .catch((cause) => { if (!cancelled && (!(cause instanceof ApiError) || cause.status !== 404)) setError((cause as Error).message); });
    return () => { cancelled = true; };
  }, [recordId]);
  useEffect(() => {
    if (!record || !validated(record)) return;
    const id = record.provider_hypothesis.hypothesis_id;
    let cancelled = false;
    api(`/diagnoses/${encodeURIComponent(id)}`, isDesignResult, undefined, "designs")
      .then((result) => { if (!cancelled && result.diagnosis_id === id) setDesignResult(result); })
      .catch((cause) => { if (!cancelled && (!(cause instanceof ApiError) || cause.status !== 404)) setError((cause as Error).message); });
    // A stored AWS-4 record belongs to one validated diagnosis; reload it on selection so the
    // supervisor never sees a stale proposal or an empty stage for an already-reviewed one.
    api(`/diagnoses/${encodeURIComponent(id)}`, isInterventionRecord, undefined, "interventions")
      .then((result) => { if (!cancelled && result.hypothesis_id === id) setInterventionRecord(result); })
      .catch((cause) => { if (!cancelled && (!(cause instanceof ApiError) || cause.status !== 404)) setError((cause as Error).message); });
    return () => { cancelled = true; };
  }, [record]);
  useEffect(() => {
    // AWS-6: a stored alignment review belongs to one design run. Load it whenever a training
    // package is shown, so a reviewed run never renders as if the review had not happened.
    if (!designResult?.training_design) return;
    const id = designResult.diagnosis_id;
    const runId = designResult.run_id;
    let cancelled = false;
    api(`/diagnoses/${encodeURIComponent(id)}/alignment-review`, isAlignmentReview, undefined, "designs")
      .then((result) => { if (!cancelled && recordRef.current === id && result.diagnosis_id === id && result.run_id === runId) setAlignmentReview(result); })
      .catch((cause) => { if (!cancelled && (!(cause instanceof ApiError) || cause.status !== 404)) setError((cause as Error).message); });
    return () => { cancelled = true; };
  }, [designResult]);

  async function refreshRecord(id: string) {
    const latest = await api(hypothesisPath(id), isRecordState);
    setRecords((current) =>
      current.map((item) =>
        item.provider_hypothesis.hypothesis_id === id ? latest : item,
      ),
    );
  }
  function begin(): boolean {
    if (busyRef.current) return false; // Ignore double clicks and overlapping mutations.
    busyRef.current = true;
    setBusy(true);
    setError(null);
    return true;
  }
  function finish() {
    busyRef.current = false;
    setBusy(false);
  }
  async function generate() {
    const signalId = selectedId;
    if (!signalId || !begin()) return;
    try {
      const created = await api(
        `${signalPath(signalId)}/hypotheses`,
        isRecordState,
        { method: "POST" },
      );
      // A hypothesis created for a signal the reviewer has since left must not appear
      // in another signal's history; the backend list reloads it when they return.
      if (
        selectedRef.current !== signalId ||
        created.provider_hypothesis.signal_id !== signalId
      )
        return;
      setRecords((current) => [created, ...current]);
      setRecordId(created.provider_hypothesis.hypothesis_id);
    } catch (cause) {
      if (selectedRef.current === signalId) setError((cause as Error).message);
    } finally {
      finish();
    }
  }
  async function mutate(
    kind: "approve" | "reject" | "revise",
    revision?: Diagnosis,
    revisionRationale?: string,
  ) {
    if (!record || !reviewer.trim() || !begin()) return;
    const id = record.provider_hypothesis.hypothesis_id;
    try {
      const body =
        kind === "revise"
          ? {
              reviewer_id: reviewer.trim(),
              rationale: revisionRationale,
              revision,
            }
          : kind === "reject"
            ? { reviewer_id: reviewer.trim(), rationale }
            : { reviewer_id: reviewer.trim() };
      const latest = await api(`${hypothesisPath(id)}/${kind}`, isRecordState, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setRecords((current) =>
        current.map((item) =>
          item.provider_hypothesis.hypothesis_id === id ? latest : item,
        ),
      );
      setAction(null);
      setRationale("");
    } catch (cause) {
      setError((cause as Error).message);
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          await refreshRecord(id);
        } catch {
          /* Keep the error visible. */
        }
      }
    } finally {
      finish();
    }
  }
  async function designIntervention() {
    if (!record || !validated(record) || !begin()) return;
    const id = record.provider_hypothesis.hypothesis_id;
    setDesigning(true);
    try {
      const result = await api(`/diagnoses/${encodeURIComponent(id)}`, isDesignResult,
        { method: "POST" }, "designs");
      if (result.diagnosis_id !== id) throw new Error("The design response did not match the selected diagnosis.");
      // A design that finished for a diagnosis the reviewer has since left must not render
      // under another hypothesis; the effect above reloads it when they return.
      if (selectedRef.current === record.provider_hypothesis.signal_id && recordRef.current === id) {
        setAlignmentReview(null);
        setDesignResult(result);
      }
    } catch (cause) {
      if (recordRef.current === id) setError((cause as Error).message);
    } finally {
      setDesigning(false);
      finish();
    }
  }
  async function checkAlignment() {
    if (!designResult?.training_design || !begin()) return;
    const id = designResult.diagnosis_id;
    const runId = designResult.run_id;
    setCheckingAlignment(true);
    try {
      const result = await api(`/diagnoses/${encodeURIComponent(id)}/alignment-review`, isAlignmentReview,
        { method: "POST" }, "designs");
      if (result.diagnosis_id !== id || result.run_id !== runId) throw new Error("The alignment review did not match the displayed design run.");
      if (recordRef.current === id) setAlignmentReview(result);
    } catch (cause) {
      if (recordRef.current === id) setError((cause as Error).message);
    } finally {
      setCheckingAlignment(false);
      finish();
    }
  }
  async function runInterventionStage(step: "propose" | "validate") {
    if (!record || !validated(record) || !begin()) return;
    const id = record.provider_hypothesis.hypothesis_id;
    setInterventionStep(step);
    try {
      const result = await api(`/diagnoses/${encodeURIComponent(id)}/${step === "propose" ? "propose" : "validate-solution"}`,
        isInterventionRecord, { method: "POST" }, "interventions");
      if (result.hypothesis_id !== id || result.signal_id !== record.provider_hypothesis.signal_id)
        throw new Error("The intervention response did not match the selected diagnosis.");
      // A stage that finishes after the reviewer moved on must not render under another diagnosis.
      if (selectedRef.current === record.provider_hypothesis.signal_id && recordRef.current === id) setInterventionRecord(result);
    } catch (cause) {
      if (recordRef.current === id) setError((cause as Error).message);
    } finally {
      setInterventionStep(null);
      finish();
    }
  }
  async function validateEvidence() {
    if (!record || !begin()) return;
    const id = record.provider_hypothesis.hypothesis_id;
    try {
      const result = await api(`${hypothesisPath(id)}/validate-evidence`, isEvidenceValidation,
        { method: "POST" });
      if (result.hypothesis_id !== id || result.signal_id !== record.provider_hypothesis.signal_id)
        throw new Error("The evidence review did not match this diagnosis.");
      if (recordRef.current === id) setEvidenceValidation(result);
    } catch (cause) {
      if (recordRef.current === id) setError((cause as Error).message);
    } finally {
      finish();
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            C<span>●</span>
          </span>
          <div>
            <strong>
              CoachLens <em>AI</em>
            </strong>
            <span>Evidence-Driven Performance Diagnosis</span>
          </div>
        </div>
        <div className="topbar-right">
          <span className="workspace-label">REVIEW WORKSPACE</span>
          <span className="milestone">MILESTONE 05</span>
        </div>
      </header>
      <main className="workspace">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">Human diagnostic validation</span>
            <h1>From QA evidence to a reviewed diagnosis.</h1>
            <p>
              Inspect the observation, challenge the hypothesis, and record the
              human decision.
            </p>
          </div>
          <div className="flow-pill">
            <span>
              01 <b>Observed</b>
            </span>
            <i>→</i>
            <span>
              02 <b>Proposed</b>
            </span>
            <i>→</i>
            <span>
              03 <b>Validated</b>
            </span>
            <i>→</i>
            <span>
              04 <b>Intervention</b>
            </span>
            <i>→</i>
            <span>
              05 <b>Solution</b>
            </span>
          </div>
        </div>
        {error && (
          <div role="alert" className="banner error">
            <strong>Action needed</strong>
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              aria-label="Dismiss error"
            >
              ×
            </button>
          </div>
        )}
        <div className="workspace-grid">
          <aside className="signal-nav" aria-label="Observed QA signals">
            <div className="rail-heading">
              <span className="eyebrow">01 / Source QA result</span>
              <h2>Observed signals</h2>
              <p>Deterministic M2 counts from validated QA records.</p>
            </div>
            {loadingSignals ? (
              <p role="status" className="state-copy">
                Loading QA signals…
              </p>
            ) : !signals.length ? (
              <div className="empty-rail">
                <p>No QA signals are available.</p>
                <span>Load normalized evaluations in the API to begin.</span>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    setLoadingSignals(true);
                    setError(null);
                    void loadSignals();
                  }}
                >
                  Retry connection ↗
                </button>
              </div>
            ) : (
              <div className="signal-list">
                {signals.map((signal) => (
                  <button
                    type="button"
                    key={signal.signal_id}
                    className={`signal-row ${selectedId === signal.signal_id ? "selected" : ""}`}
                    onClick={() => {
                      if (signal.signal_id !== selectedId) {
                        setLoadingSignal(true);
                        setSignalError(null);
                        setBundle(null);
                        setRecords([]);
                        setRecordId(null);
                        setDesignResult(null);
                        setAlignmentReview(null);
                        setInterventionRecord(null);
                        setSelectedEvidence(null);
                        setAction(null);
                        setSelectedId(signal.signal_id);
                      }
                      setError(null);
                    }}
                    aria-current={
                      selectedId === signal.signal_id ? "true" : undefined
                    }
                  >
                    <span className="signal-domain">
                      {label(signal.domain)}
                    </span>
                    <strong>{signal.criterion}</strong>
                    <span className="signal-metrics">
                      <b>
                        {signal.fail_count}/{signal.evaluated_results}
                      </b>{" "}
                      failed <span>{percent(signal.fail_rate)}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}
            <div className="rail-foot">
              Source answers and pass markers are interpreted by M2. This
              workspace does not rescore them.
            </div>
          </aside>

          <section className="review-main" aria-label="Diagnostic review">
            {!selectedSignal ? (
              <div className="main-empty">
                Select an observed QA signal to begin review.
              </div>
            ) : (
              <>
                <section className="observation">
                  <div className="section-kicker">
                    <span className="level-dot observed-dot" /> OBSERVED ·
                    DETERMINISTIC QA SIGNAL
                  </div>
                  <div className="observation-head">
                    <div>
                      <span className="domain-tag">
                        {label(selectedSignal.domain)}
                      </span>
                      <h2>{selectedSignal.criterion}</h2>
                    </div>
                    <div className="observed-rate">
                      <strong>{percent(selectedSignal.fail_rate)}</strong>
                      <span>observed failure rate</span>
                    </div>
                  </div>
                  <div className="observation-facts">
                    <div>
                      <b>
                        {selectedSignal.fail_count} of{" "}
                        {selectedSignal.evaluated_results}
                      </b>
                      <span>criterion results failed</span>
                    </div>
                    <div>
                      <b>
                        {selectedSignal.evaluated_evaluations} of{" "}
                        {selectedSignal.total_evaluations}
                      </b>
                      <span>loaded evaluations contain this criterion</span>
                    </div>
                    <div>
                      <b>{selectedSignal.feedback_count}</b>
                      <span>records contain feedback</span>
                    </div>
                  </div>
                  <p className="source-note">
                    These are structured source QA results calculated by M2.
                    They do not establish why the behavior occurred.
                  </p>
                </section>
                {loadingSignal ? (
                  <div role="status" className="loading-panel">
                    Loading evidence and review history…
                  </div>
                ) : signalError ? (
                  <div role="alert" className="empty-panel">
                    <h3>Evidence unavailable</h3>
                    <p>{signalError}</p>
                    <button
                      className="button secondary"
                      onClick={() => setSelectedId(null)}
                    >
                      Choose another signal
                    </button>
                  </div>
                ) : (
                  <>
                    <section className="lineage" aria-label="Evidence lineage">
                      <div className="section-title">
                        <span className="eyebrow">
                          Evidence graph / provenance
                        </span>
                        <h3>Trace the decision</h3>
                      </div>
                      <div className="lineage-track">
                        <div>
                          <span>Source evidence</span>
                          <strong>
                            {bundle?.items.length ?? 0} criterion rows
                          </strong>
                        </div>
                        <i>→</i>
                        <div>
                          <span>Performance signal</span>
                          <strong>{selectedSignal.criterion}</strong>
                        </div>
                        <i>→</i>
                        <div>
                          <span>Diagnostic hypothesis</span>
                          <strong>
                            {!record
                              ? "Not requested"
                              : isDemo
                                ? "Fixture proposed"
                                : "AI proposed"}
                          </strong>
                        </div>
                        <i>→</i>
                        <div>
                          <span>Human validation</span>
                          <strong>
                            {record && validated(record)
                              ? record.human_revision
                                ? "Revision approved"
                                : "Approved"
                              : record?.status === "rejected"
                                ? "Rejected"
                                : "Pending"}
                          </strong>
                        </div>
                      </div>
                    </section>
                    {records.length > 1 && (
                      <div className="history-selector">
                        <label htmlFor="hypothesis-select">
                          Review history
                        </label>
                        <select
                          id="hypothesis-select"
                          value={recordId ?? ""}
                          onChange={(event) => {
                            setRecordId(event.target.value);
                            setDesignResult(null);
                            setAlignmentReview(null);
                            setInterventionRecord(null);
                            setSelectedEvidence(null);
                            setAction(null);
                          }}
                        >
                          {records.map((entry) => (
                            <option
                              key={entry.provider_hypothesis.hypothesis_id}
                              value={entry.provider_hypothesis.hypothesis_id}
                            >
                              {shortId(entry.provider_hypothesis.hypothesis_id)}{" "}
                              ·{" "}
                              {entry.status === "revised" &&
                              entry.revision_approved
                                ? "Revised and approved"
                                : label(entry.status)}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                    {!record ? (
                      <section className="empty-panel">
                        <span className="eyebrow">
                          02 / Diagnostic hypothesis
                        </span>
                        <h3>No hypothesis for this signal yet.</h3>
                        <p>
                          Review the source evidence, then request a diagnostic
                          hypothesis through the M3 reasoning workflow. A
                          provider must be configured.
                        </p>
                        <button
                          type="button"
                          className="button primary"
                          onClick={() => void generate()}
                          disabled={busy}
                        >
                          {busy
                            ? "Generating hypothesis…"
                            : "Request diagnostic hypothesis"}
                        </button>
                      </section>
                    ) : (
                      <>
                        <section className="hypothesis">
                          <div className="section-kicker">
                            <span className="level-dot proposed-dot" />{" "}
                            {isDemo
                              ? "CONTROLLED DEMO · DIAGNOSTIC HYPOTHESIS"
                              : "AI-GENERATED · DIAGNOSTIC HYPOTHESIS"}
                          </div>
                          {isDemo && (
                            <div className="demo-notice">
                              Synthetic demo hypothesis. The fixture performs no
                              AI inference.
                            </div>
                          )}
                          <div className="hypothesis-head">
                            <div>
                              <span className="eyebrow">
                                {isDemo ? "Original fixture proposal" : "Original AI proposal"}
                              </span>
                              <h2>
                                {record.status === "rejected"
                                  ? "Rejected diagnosis"
                                  : record.human_revision
                                    ? "Original proposal · superseded by reviewer"
                                    : validated(record)
                                      ? "Original proposal · accepted by reviewer"
                                      : "Awaiting human validation"}
                              </h2>
                            </div>
                            <span
                              className={`status-badge ${
                                record.human_revision
                                  ? record.revision_approved
                                    ? "superseded"
                                    : "pending"
                                  : validated(record)
                                    ? "accepted"
                                    : record.status === "rejected"
                                      ? "rejected"
                                      : "pending"
                              }`}
                            >
                              {record.human_revision
                                ? record.revision_approved
                                  ? "SUPERSEDED"
                                  : "REVISED · NOT YET VALIDATED"
                                : validated(record)
                                  ? "ACCEPTED BY REVIEWER"
                                  : record.status === "rejected"
                                    ? "REJECTED"
                                    : "NOT YET VALIDATED"}
                            </span>
                          </div>
                          <div className="behavior">
                            <span className="field-label">
                              {isDemo
                                ? "Fixture description of observed behavior"
                                : "AI description of observed behavior"}
                            </span>
                            <p>
                              {
                                record.provider_hypothesis
                                  .observed_behavioral_defect
                              }
                            </p>
                          </div>
                          {record.human_revision && (
                            <div className="revision-separation">
                              <span>
                                {isDemo
                                  ? "ORIGINAL FIXTURE PROPOSAL · PRESERVED"
                                  : "ORIGINAL AI PROPOSAL · PRESERVED"}
                              </span>
                              <p>
                                The proposal below remains part of the audit
                                history. The reviewer’s correction follows
                                separately.
                              </p>
                            </div>
                          )}
                          <DiagnosisBody
                            diagnosis={record.provider_hypothesis}
                            confidence={
                              record.provider_hypothesis
                                .provider_reported_confidence
                            }
                            demo={isDemo}
                            onSelect={setSelectedEvidence}
                          />
                          <div className="provider-meta">
                            Provider:{" "}
                            {
                              record.provider_hypothesis.provider_metadata
                                .provider
                            }
                            {record.provider_hypothesis.provider_metadata.model
                              ? ` · ${record.provider_hypothesis.provider_metadata.model}`
                              : ""}
                          </div>
                        </section>
                        <section className="validation" aria-label="Semantic evidence review">
                          <div className="section-kicker">02A / SEMANTIC EVIDENCE REVIEW</div>
                          <h2>Does the evidence support the proposed diagnosis?</h2>
                          {currentValidation ? (
                            <>
                              <div className={`working-diagnosis semantic-verdict ${currentValidation.semantic_status === "evidence_validated" ? "" : "questioned"}`}>
                                <strong>{label(currentValidation.validation_outcome)}</strong>
                                <span>{currentValidation.semantic_status === "evidence_validated" ? "EVIDENCE VALIDATED" : "EVIDENCE QUESTIONED"}</span>
                                <small>
                                  {isDemo ? "Fixed fixture review of the original fixture proposal." : "AI review of the original AI proposal."}{" "}
                                  Not a human decision.
                                </small>
                              </div>
                              <p>{currentValidation.support_assessment}</p>
                              <div className="evidence-pair">
                                <EvidenceGroup
                                  title="Evidence the validator confirms as support"
                                  references={currentValidation.supported_evidence}
                                  kind="supporting"
                                  onSelect={setSelectedEvidence}
                                />
                                <EvidenceGroup
                                  title="Evidence the validator finds contradicting"
                                  references={currentValidation.contradicting_evidence}
                                  kind="conflicting"
                                  onSelect={setSelectedEvidence}
                                />
                              </div>
                              {currentValidation.unsupported_claims.length > 0 && <div className="missing"><h4>Claims beyond the evidence</h4><ul>{currentValidation.unsupported_claims.map((claim, index) => <li key={index}>{claim}</li>)}</ul></div>}
                              {currentValidation.missing_evidence.length > 0 && <div className="missing"><h4>Evidence still needed</h4><ul>{currentValidation.missing_evidence.map((gap, index) => <li key={index}>{gap}</li>)}</ul></div>}
                              <div className="confidence">
                                <div>
                                  <span className="field-label">{isDemo ? "Fixture support confidence" : "Validator-reported support confidence"}</span>
                                  <strong>{currentValidation.provider_reported_confidence}</strong>
                                </div>
                                <p>How strongly the supplied evidence supports the proposal as written. It is not a statistically calibrated probability.</p>
                              </div>
                              {record.human_revision ? (
                                <p>This review assessed the original proposal only. The reviewer’s revision below has not been semantically reviewed.</p>
                              ) : (
                                <p>This review does not approve or reject the diagnosis. A human reviewer decides below.</p>
                              )}
                            </>
                          ) : record.status === "awaiting_review" ? (
                            <>
                              <p>Ask the evidence validator whether the same evidence population the reasoner saw, including evidence it did not cite, supports this proposal. The result informs the human decision below and never replaces it.</p>
                              <button type="button" className="button secondary" disabled={busy}
                                onClick={() => void validateEvidence()}>Validate evidence</button>
                            </>
                          ) : (
                            <p>No semantic evidence review was recorded before the reviewer’s decision.</p>
                          )}
                        </section>
                        {record.human_revision && (
                          <section className="human-revision">
                            <div className="section-kicker">
                              <span className="level-dot human-dot" /> HUMAN
                              REVISION ·{" "}
                              {record.revision_approved
                                ? "APPROVED"
                                : "PENDING APPROVAL"}
                            </div>
                            <h2>Reviewer correction</h2>
                            <div className="behavior">
                              <span className="field-label">
                                Corrected behavioral defect
                              </span>
                              <p>
                                {
                                  record.human_revision
                                    .observed_behavioral_defect
                                }
                              </p>
                            </div>
                            <DiagnosisBody
                              diagnosis={record.human_revision}
                              human
                              onSelect={setSelectedEvidence}
                            />
                          </section>
                        )}
                        <section className="validation">
                          <div className="section-kicker">
                            <span className="level-dot human-dot" /> 03 / HUMAN
                            VALIDATION
                          </div>
                          {validated(record) ? (
                            <>
                              <span className="validation-step">↓ Accepted by reviewer</span>
                              <h2>Working diagnosis</h2>
                              <div className="working-diagnosis">
                                <strong>{label(currentDiagnosis!.cause_domain)} · {label(currentDiagnosis!.performance_dimension)}</strong>
                                <span>HUMAN VALIDATED</span>
                                <small>{record.human_revision ? "Human-revised working diagnosis" : isDemo ? "Accepted original fixture proposal" : "Accepted original AI proposal"}</small>
                              </div>
                              <p>
                                Approval records a human
                                decision; it does not establish objective causal
                                truth, and reviewer identifiers are not
                                authenticated.
                              </p>
                              <div className="decision-meta">
                                Approved by{" "}
                                <strong>
                                  {
                                    record.events.find(
                                      (event) => event.action === "approve",
                                    )?.reviewer_id
                                  }
                                </strong>{" "}
                                ·{" "}
                                {record.events.find(
                                  (event) => event.action === "approve",
                                )?.occurred_at
                                  ? new Date(
                                      record.events.find(
                                        (event) => event.action === "approve",
                                      )!.occurred_at,
                                    ).toLocaleString()
                                  : ""}
                              </div>
                              {!designResult && <div className="ready">READY FOR INTERVENTION REVIEW <span>→</span></div>}
                              <InterventionPanel
                                record={currentIntervention}
                                humanRevised={record.human_revision !== null}
                                busy={busy}
                                onPropose={() => void runInterventionStage("propose")}
                                onValidate={() => void runInterventionStage("validate")}
                                onSelect={setSelectedEvidence}
                              />
                              {interventionStep === "propose" && <p role="status">Proposing intervention…</p>}
                              {interventionStep === "validate" && <p role="status">Validating the proposed solution…</p>}
                              {!designResult && currentIntervention?.status === "solution_questioned" && (
                                <p className="design-withheld" role="note">{trainingGate === "withheld" ? "Training design is withheld. The solution review questioned the proposed training, so nothing is handed to the M5 training generator." : "M5 handoff is withheld. The solution review questioned the proposed intervention."} A corrected proposal needs a new diagnosis review run.</p>
                              )}
                              {!designResult && currentIntervention?.status === "solution_validated" && <>
                                <p className="design-transition">
                                  {trainingGate === "permitted"
                                    ? "Design Intervention hands the solution-reviewed proposal to M5, which drafts a training outline, activities, and practice for independent alignment review."
                                    : "Design Intervention records the non-training decision in M5. No training outline, activities, practice, or rubric will be generated."}
                                </p>
                                <button type="button" className="button primary" disabled={busy || designing} onClick={() => void designIntervention()}>DESIGN INTERVENTION</button>
                              </>}
                              {designing && <p role="status">Designing intervention and learning experience…</p>}
                              {designResult && <DesignWorkspace result={designResult} signalLabel={selectedSignal.criterion}
                                alignmentReview={alignmentReview?.diagnosis_id === recordId ? alignmentReview : null} checkingAlignment={checkingAlignment}
                                alignmentDisabled={busy} onCheckAlignment={() => void checkAlignment()} />}
                            </>
                          ) : record.status === "rejected" ? (
                            <>
                              <h2>Diagnosis rejected</h2>
                              <p>
                                This hypothesis did not pass human review. It is
                                not ready for design.
                              </p>
                              <div className="decision-meta">
                                Rejected by{" "}
                                <strong>
                                  {
                                    record.events.find(
                                      (event) => event.action === "reject",
                                    )?.reviewer_id
                                  }
                                </strong>{" "}
                                ·{" "}
                                {
                                  record.events.find(
                                    (event) => event.action === "reject",
                                  )?.rationale
                                }
                              </div>
                              <button
                                type="button"
                                className="button secondary"
                                disabled={busy}
                                onClick={() => void generate()}
                              >
                                Request another hypothesis
                              </button>
                            </>
                          ) : (
                            <>
                              <h2>This diagnosis has not been human validated.</h2>
                              <p>
                                Inspect supporting and conflicting evidence
                                before deciding. Approval accepts the{" "}
                                {record.status === "revised"
                                  ? "human revision"
                                  : isDemo
                                    ? "demo proposal"
                                    : "AI proposal"}{" "}
                                for the workflow.
                              </p>
                              <label className="reviewer-label">
                                Reviewer identifier{" "}
                                <input
                                  required
                                  value={reviewer}
                                  onChange={(event) =>
                                    setReviewer(event.target.value)
                                  }
                                  placeholder="Your reviewer ID"
                                  autoComplete="username"
                                />
                              </label>
                              {record.status === "awaiting_review" && (
                                <>
                                  <div className="review-actions">
                                    <button
                                      type="button"
                                      className="button danger"
                                      disabled={busy || !reviewer.trim()}
                                      onClick={() => setAction("reject")}
                                    >
                                      Reject
                                    </button>
                                    <button
                                      type="button"
                                      className="button secondary"
                                      disabled={busy || !reviewer.trim()}
                                      onClick={() => setAction("revise")}
                                    >
                                      Revise
                                    </button>
                                    <button
                                      type="button"
                                      className="button primary"
                                      disabled={busy || !reviewer.trim()}
                                      onClick={() => void mutate("approve")}
                                    >
                                      {busy
                                        ? "Saving decision…"
                                        : "Approve diagnosis"}
                                    </button>
                                  </div>
                                  {action === "reject" && (
                                    <form
                                      className="decision-form"
                                      onSubmit={(event) => {
                                        event.preventDefault();
                                        void mutate("reject");
                                      }}
                                    >
                                      <label>
                                        Reason for rejection{" "}
                                        <textarea
                                          required
                                          value={rationale}
                                          onChange={(event) =>
                                            setRationale(event.target.value)
                                          }
                                        />
                                      </label>
                                      <div className="form-actions">
                                        <button
                                          type="button"
                                          className="button secondary"
                                          onClick={() => setAction(null)}
                                        >
                                          Cancel
                                        </button>
                                        <button
                                          className="button danger"
                                          disabled={busy || !rationale.trim()}
                                        >
                                          Confirm rejection
                                        </button>
                                      </div>
                                    </form>
                                  )}
                                  {action === "revise" && (
                                    <RevisionForm
                                      original={record.provider_hypothesis}
                                      bundle={bundle}
                                      reviewer={reviewer}
                                      onCancel={() => setAction(null)}
                                      onSubmit={(revision, reason) =>
                                        void mutate("revise", revision, reason)
                                      }
                                      busy={busy}
                                      demo={isDemo}
                                    />
                                  )}
                                </>
                              )}
                              {record.status === "revised" && (
                                <div className="review-actions">
                                  <button
                                    type="button"
                                    className="button primary"
                                    disabled={busy || !reviewer.trim()}
                                    onClick={() => void mutate("approve")}
                                  >
                                    {busy
                                      ? "Saving decision…"
                                      : "Approve human revision"}
                                  </button>
                                </div>
                              )}
                            </>
                          )}
                          {record.events.length > 0 && (
                            <div className="audit">
                              <h3>Review history</h3>
                              <ol>
                                {record.events.map((event, index) => (
                                  <li key={index}>
                                    <strong>{label(event.action)}</strong> by{" "}
                                    {event.reviewer_id} ·{" "}
                                    {new Date(
                                      event.occurred_at,
                                    ).toLocaleString()}
                                    {event.rationale && (
                                      <p>{event.rationale}</p>
                                    )}
                                  </li>
                                ))}
                              </ol>
                            </div>
                          )}
                        </section>
                      </>
                    )}
                  </>
                )}
              </>
            )}
          </section>

          <aside className="inspector" aria-label="Evidence inspector">
            <div className="rail-heading">
              <span className="eyebrow">Source evidence</span>
              <h2>Evidence inspector</h2>
              <p>Review exact QA rows and citation relationships.</p>
            </div>
            {!selectedSignal ? (
              <p className="state-copy">Select a QA signal.</p>
            ) : !bundle ? (
              <p className="state-copy">
                {loadingSignal
                  ? "Loading source evidence…"
                  : "Evidence unavailable."}
              </p>
            ) : (
              <>
                <div className="inspector-tabs">
                  <span>{bundle.items.length} criterion rows</span>
                  <span>
                    {record
                      ? `${currentDiagnosis?.supporting_evidence.length ?? 0} supporting · ${currentDiagnosis?.conflicting_evidence.length ?? 0} conflicting`
                      : "No citations yet"}
                  </span>
                </div>
                {record &&
                  (currentDiagnosis?.conflicting_evidence.length ?? 0) > 0 && (
                    <div className="challenge-callout">
                      Conflicting evidence is present. Inspect it before
                      approval.
                    </div>
                  )}
                <div className="evidence-list">
                  {bundle.items.map((item, index) => {
                    const ref = {
                      item_id: item.item_id,
                      evaluation_id: item.evaluation_id,
                    };
                    const cited = relation(ref, currentDiagnosis);
                    return (
                      <button
                        type="button"
                        key={item.item_id}
                        className={`inspector-row ${selectedEvidence?.item_id === item.item_id ? "active" : ""}`}
                        onClick={() => setSelectedEvidence(ref)}
                        aria-pressed={
                          selectedEvidence?.item_id === item.item_id
                        }
                      >
                        <span className="item-number">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <span>
                          <strong>
                            Evaluation {shortId(item.evaluation_id)}
                          </strong>
                          <small>
                            {item.passed ? "Source QA pass" : "Source QA fail"}{" "}
                            · {cited === "uncited" ? "Uncited" : label(cited)}
                          </small>
                        </span>
                        <span aria-hidden="true">↗</span>
                      </button>
                    );
                  })}
                </div>
                <div className="evidence-detail" aria-live="polite">
                  {selectedEvidence?.item_id === "signal" ? (
                    <>
                      <span className="eyebrow">Aggregate citation</span>
                      <h3>Performance signal</h3>
                      <p>
                        {selectedSignal.fail_count} of{" "}
                        {selectedSignal.evaluated_results} criterion rows
                        failed, an observed failure rate of{" "}
                        {percent(selectedSignal.fail_rate)}.
                      </p>
                      <p className="quiet">
                        This aggregate has no individual evaluation ID. Select a
                        criterion row for source lineage.
                      </p>
                    </>
                  ) : evidenceItem ? (
                    <>
                      <span className="eyebrow">
                        {label(relation(selectedEvidence!, currentDiagnosis))}{" "}
                        evidence · source QA result
                      </span>
                      <h3>Evaluation {shortId(evidenceItem.evaluation_id)}</h3>
                      <dl>
                        <div>
                          <dt>Evaluation reference</dt>
                          <dd className="mono">{evidenceItem.evaluation_id}</dd>
                        </div>
                        <div>
                          <dt>Criterion</dt>
                          <dd>{evidenceItem.criterion}</dd>
                        </div>
                        <div>
                          <dt>Source answer / result</dt>
                          <dd>
                            {evidenceItem.answer} ·{" "}
                            {evidenceItem.passed ? "Pass" : "Fail"}
                          </dd>
                        </div>
                        <div>
                          <dt>Score</dt>
                          <dd>
                            {evidenceItem.attained_score} /{" "}
                            {evidenceItem.max_score}
                          </dd>
                        </div>
                        <div>
                          <dt>Workbook / sheet / row</dt>
                          <dd>
                            {evidenceItem.source_lineage.source_filename} ·{" "}
                            {evidenceItem.source_lineage.source_sheet} ·{" "}
                            {evidenceItem.source_lineage.excel_row}
                          </dd>
                        </div>
                      </dl>
                      <div className="feedback">
                        <span className="field-label">Evaluator feedback</span>
                        <p>
                          {evidenceItem.evaluator_feedback ??
                            "No feedback recorded for this row."}
                        </p>
                      </div>
                      <p className="privacy-note">
                        Reviewer evidence may contain sensitive feedback.
                        Internal IDs minimize identity; they do not anonymize
                        this data.
                      </p>
                    </>
                  ) : selectedEvidence ? (
                    <>
                      <h3>Citation not in this signal’s evidence</h3>
                      <p>
                        The cited item {shortId(selectedEvidence.item_id)} is
                        not one of this signal’s source rows. Refresh before
                        relying on it.
                      </p>
                    </>
                  ) : (
                    <>
                      <h3>Select evidence to inspect</h3>
                      <p>
                        Choose a row above or a citation in the hypothesis to
                        see its source and relationship.
                      </p>
                    </>
                  )}
                </div>
              </>
            )}
          </aside>
        </div>
      </main>
      <footer className="footer">
        CoachLens AI · Review Workspace{" "}
        <span>
          M5 extends human-validated diagnosis to a proposed intervention. Independent alignment review begins in a later
          milestone.
        </span>
      </footer>
    </div>
  );
}
