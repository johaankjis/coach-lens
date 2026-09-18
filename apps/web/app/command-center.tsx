"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { RevisionForm } from "./revision-form";
import {
  api,
  ApiError,
  isEvidenceBundle,
  isRecordState,
  shortId,
  type Diagnosis,
  type EvidenceBundle,
  type EvidenceReference,
  type RecordState,
} from "../lib/diagnostics";
import { loadHomeSources } from "../lib/home/load";
import {
  AGENT_INSIGHTS_PATH,
  buildHomeReadModel,
  DEMO_FIXTURE_PROVIDER,
  type AlignmentStage,
  type EvidenceReviewStatus,
  type HomeReadModel,
  type HomeSources,
  type HumanValidationStatus,
  type InterventionStage,
  type PriorityInsight,
  type StatusTone,
  type SummaryMetric,
  type TrainingStage,
} from "../lib/home/read-model";

/* ---------- Status vocabulary ----------------------------------------------------------
 * Tone classes are deliberately separate from meaning: semantic "questioned" is caution
 * (amber), never the red reserved for a human rejection. */
export function Pill({ tone, children }: { tone: StatusTone; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function evidenceReviewPill(status: EvidenceReviewStatus): { tone: StatusTone; text: string } {
  switch (status.state) {
    case "not_applicable":
      return { tone: "neutral", text: "No diagnosis yet" };
    case "not_run":
      return { tone: "neutral", text: "Not yet reviewed" };
    case "evidence_validated":
      return { tone: "validated", text: `Evidence validated · ${status.outcome}` };
    case "evidence_questioned":
      return { tone: "caution", text: `Evidence questioned · ${status.outcome}` };
  }
}

function humanValidationPill(status: HumanValidationStatus): { tone: StatusTone; text: string } {
  switch (status.state) {
    case "none":
      return { tone: "neutral", text: "No diagnosis to validate" };
    case "awaiting_review":
      return { tone: "pending", text: "Awaiting review" };
    case "approved":
      return { tone: "validated", text: "Approved" };
    case "revised_pending":
      return { tone: "caution", text: "Revised · awaiting approval" };
    case "revised_approved":
      return { tone: "validated", text: "Revised · approved" };
    case "rejected":
      return { tone: "rejected", text: "Rejected" };
  }
}

export function interventionPill(stage: InterventionStage): { tone: StatusTone; text: string } {
  switch (stage.state) {
    case "blocked":
      return { tone: "neutral", text: "Requires human-validated diagnosis" };
    case "not_started":
      return { tone: "neutral", text: "Not proposed" };
    case "proposed":
      return { tone: "proposed", text: `${stage.typeLabel} proposed · solution not validated` };
    case "solution_validated":
      return { tone: "validated", text: `${stage.typeLabel} · solution validated` };
    case "solution_questioned":
      return { tone: "caution", text: `${stage.typeLabel} · solution questioned` };
  }
}

export function trainingPill(stage: TrainingStage): { tone: StatusTone; text: string } {
  switch (stage.state) {
    case "blocked":
      return { tone: "neutral", text: "Blocked upstream" };
    case "awaiting_solution":
      return { tone: "neutral", text: "Awaiting solution validation" };
    case "withheld":
      return { tone: "caution", text: "Training withheld" };
    case "not_applicable":
      return { tone: "not_applicable", text: "Training not applicable" };
    case "permitted":
      return { tone: "pending", text: "Ready to generate · not generated" };
    case "generated":
      return { tone: "validated", text: "Training generated · not deployed" };
  }
}

/** AWS-6 semantic verdict. "Design aligned" is never "Solution validated" or "Outcome validated". */
export function alignmentPill(stage: AlignmentStage): { tone: StatusTone; text: string } {
  switch (stage.state) {
    case "blocked":
      return { tone: "neutral", text: "Blocked upstream" };
    case "not_applicable":
      return { tone: "not_applicable", text: "Not applicable" };
    case "pending":
      return { tone: "pending", text: "Pending · not yet reviewed" };
    case "design_aligned":
      return { tone: "validated", text: `Design aligned · ${stage.outcomeLabel}` };
    case "design_questioned":
      return { tone: "caution", text: `Design questioned · ${stage.outcomeLabel}` };
  }
}

/** One-line summary of what the AWS-6 reviewer flagged; counts only, never a recomputed score. */
export function alignmentFlagSummary(stage: Extract<AlignmentStage, { state: "design_aligned" | "design_questioned" }>): string {
  const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;
  return `${count(stage.problematicElements.length, "problematic element")} · ${count(stage.unsupportedAssumptions.length, "unsupported assumption")} · ${stage.missingInformation.length} missing information item${stage.missingInformation.length === 1 ? "" : "s"}`;
}

const referenceName = (reference: EvidenceReference) =>
  reference.item_id === "signal" ? "Aggregate QA signal" : `Evaluation ${shortId(reference.evaluation_id ?? "")}`;

/* ---------- Human validation controls ---------------------------------------------------
 * Home records the M4 decision through the same endpoints Agent Insights uses:
 * `POST /hypotheses/{id}/approve`, `/reject`, and `/revise`. The container owns the request;
 * the panel below only collects the reviewer's input. */
export type ValidationDecision =
  | { kind: "approve"; reviewer: string }
  | { kind: "reject"; reviewer: string; rationale: string }
  | { kind: "revise"; reviewer: string; rationale: string; revision: Diagnosis };

export type ValidationControls = {
  /** The M3 review record Home summarizes, or null when no diagnosis exists. */
  record: RecordState | null;
  busy: boolean;
  error: string | null;
  onDecide: (decision: ValidationDecision) => void;
  /** Source evidence rows for the revision form's citation relationships. */
  loadBundle: (signalId: string) => Promise<EvidenceBundle>;
  /** Reviewer identifier kept by the page so it survives a reload after a decision. */
  reviewer?: string;
  onReviewerChange?: (reviewer: string) => void;
};

/* ---------- Sections ------------------------------------------------------------------- */

function ProvenanceBadge({ model }: { model: HomeReadModel }) {
  const { provenance } = model;
  return (
    <div className={`provenance ${provenance.kind}`} role="note" aria-label="Data provenance">
      <strong>{provenance.label}</strong>
      <span>{provenance.detail}</span>
      <small>
        Diagnostic provider: {provenance.diagnosticProvider} · Intervention provider:{" "}
        {provenance.interventionProvider} · Design provider: {provenance.designProvider}
      </small>
    </div>
  );
}

const STAT_ICONS: Record<SummaryMetric["id"], ReactNode> = {
  evaluations: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v4h4" />
      <path d="M9 12h6" />
      <path d="M9 16h6" />
    </svg>
  ),
  criteria: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 6h3" />
      <path d="M4 12h3" />
      <path d="M4 18h3" />
      <path d="M10 6h10" />
      <path d="M10 12h10" />
      <path d="M10 18h10" />
    </svg>
  ),
  gap: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 19V13" />
      <path d="M12 19V8" />
      <path d="M19 19V4" />
      <path d="M3 19h18" />
    </svg>
  ),
  workflow: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="5" cy="12" r="2.2" />
      <circle cx="12" cy="12" r="2.2" />
      <circle cx="19" cy="12" r="2.2" />
      <path d="M7.2 12h2.6" />
      <path d="M14.2 12h2.6" />
    </svg>
  ),
};

/**
 * One top metric. `available` and `empty` readings carry the value the read-model derived from
 * backend state; `pending` and `unavailable` say why no value exists. Nothing here computes.
 */
function StatTile({ metric }: { metric: SummaryMetric }) {
  const { reading } = metric;
  return (
    <article className={`stat-tile ${metric.id} ${reading.state}`} aria-labelledby={`stat-${metric.id}`}>
      <span className="stat-icon">{STAT_ICONS[metric.id]}</span>
      <div className="stat-body">
        {reading.state === "available" || reading.state === "empty" ? (
          <>
            <p className={`stat-value ${reading.state === "empty" ? "muted" : ""} ${metric.id === "workflow" ? "state" : ""}`}>
              {reading.value}
            </p>
            <h3 id={`stat-${metric.id}`}>{metric.label}</h3>
            <p className="stat-detail">{reading.detail}</p>
          </>
        ) : (
          <>
            <p className="stat-value muted">{reading.state === "pending" ? "Pending" : "Unavailable"}</p>
            <h3 id={`stat-${metric.id}`}>{metric.label}</h3>
            {reading.state === "pending" && reading.note && <p className="stat-note">{reading.note}</p>}
            <p className="stat-detail">{reading.reason}</p>
          </>
        )}
        <p className="stat-source">Source: {metric.source}</p>
      </div>
    </article>
  );
}

function PerformanceGaps({
  model,
  onSelectSignal,
  disabled = false,
}: {
  model: HomeReadModel;
  onSelectSignal?: (signalId: string) => void;
  disabled?: boolean;
}) {
  const selectedId = model.priority?.signalId ?? null;
  return (
    <section className="home-card gaps" aria-labelledby="gaps-title">
      <div className="home-card-head">
        <div>
          <h2 id="gaps-title">Performance gaps</h2>
          <p className="card-sub">Observed QA criteria · M2 counts in backend order</p>
        </div>
      </div>
      {model.gaps.length === 0 ? (
        <div className="home-empty">
          <p>No QA signals are loaded.</p>
          <span>Load normalized evaluations in the API to see observed criteria here.</span>
        </div>
      ) : (
        <ol className="gap-list" aria-label="Observed QA criteria">
          {model.gaps.map((gap) => {
            const selected = gap.signalId === selectedId;
            return (
              <li key={gap.signalId} className={`gap-row ${selected ? "selected" : ""}`}>
                <button
                  type="button"
                  className="gap-select"
                  aria-pressed={selected}
                  disabled={disabled}
                  onClick={() => onSelectSignal?.(gap.signalId)}
                >
                  <span className="gap-title">
                    <span className="gap-name">{gap.criterion}</span>
                    <span className="gap-domain">{gap.domain}</span>
                  </span>
                  <span className="gap-track">
                    <span
                      className="gap-bar"
                      role="img"
                      aria-label={`Observed failure rate ${gap.failRateLabel}`}
                    >
                      <span style={{ width: `${Math.round(gap.failRateFraction * 100)}%` }} />
                    </span>
                    <b className="gap-rate">{gap.failRateLabel}</b>
                  </span>
                  <span className="gap-meta">
                    {gap.failCount}/{gap.evaluatedResults} results failed · {gap.coverage.evaluated} of{" "}
                    {gap.coverage.total} evaluations
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
      <p className="source-note">
        Ordered by failure count, then failure rate. The order does not establish severity, priority, or cause.
      </p>
      {model.observedSignalCount > 0 && (
        <Link className="button ghost" href={AGENT_INSIGHTS_PATH}>
          View all {model.observedSignalCount} observed criteria →
        </Link>
      )}
    </section>
  );
}

export function Pipeline({ insight }: { insight: PriorityInsight }) {
  return (
    <ol className="pipeline" aria-label="Progress of this insight through the workflow">
      {insight.pipeline.map((step) => (
        <li key={step.id} className={`pipeline-step ${step.tone}`}>
          <span className="pipeline-name">{step.name}</span>
          <span className="pipeline-state">{step.text}</span>
        </li>
      ))}
    </ol>
  );
}

/** The human decision on the working diagnosis, recorded through the existing M4 endpoints. */
function HumanValidationPanel({
  insight,
  controls,
}: {
  insight: PriorityInsight;
  controls?: ValidationControls;
}) {
  const status = insight.humanValidation;
  const record =
    controls?.record && controls.record.provider_hypothesis.signal_id === insight.signalId ? controls.record : null;
  const busy = controls?.busy ?? false;
  const [localReviewer, setLocalReviewer] = useState("");
  const reviewer = controls?.reviewer ?? localReviewer;
  const setReviewer = controls?.onReviewerChange ?? setLocalReviewer;
  const [needReviewer, setNeedReviewer] = useState(false);
  const [action, setAction] = useState<"reject" | "revise" | null>(null);
  const [rationale, setRationale] = useState("");
  const [bundle, setBundle] = useState<EvidenceBundle | null>(null);
  const [bundleState, setBundleState] = useState<"idle" | "loading" | "error">("idle");
  const reviewerInput = useRef<HTMLInputElement>(null);
  const pill = humanValidationPill(status);
  const demo = record?.provider_hypothesis.provider_metadata.provider === DEMO_FIXTURE_PROVIDER;

  const withReviewer = (next: (reviewerId: string) => void) => {
    const id = reviewer.trim();
    if (!id) {
      setNeedReviewer(true);
      reviewerInput.current?.focus();
      return;
    }
    setNeedReviewer(false);
    next(id);
  };
  const openRevise = async () => {
    setAction("revise");
    if (bundle || !controls) return;
    setBundleState("loading");
    try {
      const loaded = await controls.loadBundle(insight.signalId);
      if (loaded.signal.signal_id !== insight.signalId) throw new Error("Evidence does not match the selected signal.");
      setBundle(loaded);
      setBundleState("idle");
    } catch {
      setBundleState("error");
    }
  };
  const reviewerField = (
    <label className="reviewer-inline">
      <span>Reviewer ID</span>
      <input
        ref={reviewerInput}
        value={reviewer}
        onChange={(event) => {
          setReviewer(event.target.value);
          if (event.target.value.trim()) setNeedReviewer(false);
        }}
        placeholder="Your reviewer ID"
        autoComplete="username"
        aria-invalid={needReviewer || undefined}
        aria-describedby={needReviewer ? "reviewer-hint" : undefined}
      />
      {needReviewer && (
        <span id="reviewer-hint" className="reviewer-hint" role="alert">
          Enter your reviewer ID to record a decision.
        </span>
      )}
    </label>
  );

  return (
    <div className={`review-block human ${status.state}`}>
      <div className="review-block-head">
        <span className="field-label">Human validation</span>
        <Pill tone={pill.tone}>{pill.text}</Pill>
      </div>

      {status.state === "none" && (
        <small>No diagnosis has been proposed, so there is nothing to validate yet.</small>
      )}

      {status.state === "awaiting_review" && (
        <>
          <small>
            Approve, revise, or reject the working diagnosis. The decision is recorded through the M4 review
            workflow and is not a decision on any intervention.
          </small>
          {record && controls ? (
            <>
              {reviewerField}
              <div className="decision-group" role="group" aria-label="Human validation decision">
                <button
                  type="button"
                  className="decision approve"
                  disabled={busy}
                  onClick={() => withReviewer((id) => controls.onDecide({ kind: "approve", reviewer: id }))}
                >
                  {busy ? "Saving…" : "Approve"}
                </button>
                <button
                  type="button"
                  className={`decision revise ${action === "revise" ? "open" : ""}`}
                  aria-expanded={action === "revise"}
                  disabled={busy}
                  onClick={() => withReviewer(() => void openRevise())}
                >
                  Revise
                </button>
                <button
                  type="button"
                  className={`decision reject ${action === "reject" ? "open" : ""}`}
                  aria-expanded={action === "reject"}
                  disabled={busy}
                  onClick={() => withReviewer(() => setAction("reject"))}
                >
                  Reject
                </button>
              </div>
              {action === "reject" && (
                <form
                  className="decision-form"
                  aria-label="Reject diagnosis"
                  onSubmit={(event) => {
                    event.preventDefault();
                    withReviewer((id) => controls.onDecide({ kind: "reject", reviewer: id, rationale: rationale.trim() }));
                  }}
                >
                  <label>
                    Reason for rejection{" "}
                    <textarea required value={rationale} onChange={(event) => setRationale(event.target.value)} />
                  </label>
                  <div className="form-actions">
                    <button type="button" className="button secondary" onClick={() => setAction(null)}>
                      Cancel
                    </button>
                    <button className="button danger" disabled={busy || !rationale.trim()}>
                      Confirm rejection
                    </button>
                  </div>
                </form>
              )}
              {action === "revise" && (
                <div className="revision-inline" aria-label="Revise diagnosis">
                  {bundleState === "loading" ? (
                    <p role="status" className="state-copy">
                      Loading source evidence references…
                    </p>
                  ) : bundleState === "error" ? (
                    <div className="banner" role="alert">
                      <p>Source evidence references could not be loaded. Review them before revising.</p>
                      <button type="button" className="button secondary" onClick={() => void openRevise()}>
                        Retry references
                      </button>{" "}
                      <Link href={insight.reviewHref}>Open Agent Insights</Link>
                    </div>
                  ) : (
                    <RevisionForm
                        key={bundle ? "with-bundle" : "signal-only"}
                        original={record.provider_hypothesis}
                        bundle={bundle}
                        reviewer={reviewer}
                        onCancel={() => setAction(null)}
                        onSubmit={(revision, reason) =>
                          withReviewer((id) => controls.onDecide({ kind: "revise", reviewer: id, rationale: reason, revision }))
                        }
                        busy={busy}
                        demo={demo}
                    />
                  )}
                </div>
              )}
            </>
          ) : (
            <small>
              <Link href={insight.reviewHref}>Record the decision in Agent Insights</Link>
            </small>
          )}
        </>
      )}

      {status.state === "revised_pending" && (
        <>
          <p className="review-summary">
            The reviewer&apos;s correction{status.reviewer ? ` by ${status.reviewer}` : ""} is now the authoritative
            working diagnosis shown above. The original proposal is preserved in the record. The revision still
            needs its own approval before any intervention.
          </p>
          {status.rationale && (
            <small>
              <b>Reason for revision:</b> {status.rationale}
            </small>
          )}
          {record && controls ? (
            <>
              {reviewerField}
              <div className="decision-group" role="group" aria-label="Human validation decision">
                <button
                  type="button"
                  className="decision approve"
                  disabled={busy}
                  onClick={() => withReviewer((id) => controls.onDecide({ kind: "approve", reviewer: id }))}
                >
                  {busy ? "Saving…" : "Approve human revision"}
                </button>
              </div>
            </>
          ) : (
            <small>
              <Link href={insight.reviewHref}>Approve the revision in Agent Insights</Link>
            </small>
          )}
        </>
      )}

      {(status.state === "approved" || status.state === "revised_approved") && (
        <p className="review-summary">
          {status.state === "revised_approved"
            ? "The human-revised diagnosis is approved and authoritative. "
            : "The working diagnosis is approved. "}
          {status.reviewer ? `Recorded by ${status.reviewer}. ` : ""}
          This is a human decision on the diagnosis, not on any intervention, training, or outcome.
        </p>
      )}

      {status.state === "rejected" && (
        <>
          <p className="review-summary">
            The diagnosis was rejected{status.reviewer ? ` by ${status.reviewer}` : ""}. Downstream stages are
            blocked: no intervention, training package, or alignment review can run on it.
          </p>
          {status.rationale && (
            <small>
              <b>Reason:</b> {status.rationale}
            </small>
          )}
        </>
      )}

      {controls?.error && (
        <p role="alert" className="banner error inline">
          <strong>Decision not recorded</strong>
          <span>{controls.error}</span>
        </p>
      )}
    </div>
  );
}

/** Compact downstream rows: AWS-4, AWS-5, AWS-6, and outcome measurement, each in its own words. */
function DownstreamRows({ insight }: { insight: PriorityInsight }) {
  const { intervention, training, alignment, outcome } = insight;
  const interventionTone = interventionPill(intervention);
  const trainingTone = trainingPill(training);
  const alignmentTone = alignmentPill(alignment);
  const proposed =
    intervention.state === "proposed" ||
    intervention.state === "solution_validated" ||
    intervention.state === "solution_questioned";
  const reviewed = intervention.state === "solution_validated" || intervention.state === "solution_questioned";
  return (
    <div className="downstream-rows" role="list" aria-label="Downstream stages">
      <div className="insight-field" role="listitem">
        <span className="field-label">Intervention</span>
        <Pill tone={interventionTone.tone}>{interventionTone.text}</Pill>
        {proposed ? (
          <small>
            <b>{intervention.recommendation}</b> Target change: {intervention.targetChange}{" "}
            {intervention.origin === "fixture" ? "· Fixed fixture proposal." : "· AI proposal."} Not a human decision.
          </small>
        ) : (
          <small>
            {intervention.state === "blocked"
              ? "The AWS-4 reasoner runs only after a human validates the diagnosis."
              : "Ask the AWS-4 reasoner in Agent Insights. Training is one option, not the default."}
          </small>
        )}
      </div>
      <div className="insight-field" role="listitem">
        <span className="field-label">Solution validation</span>
        {reviewed ? (
          <>
            <Pill tone={intervention.state === "solution_validated" ? "validated" : "caution"}>
              {intervention.state === "solution_validated" ? "Solution validated" : "Solution questioned"} ·{" "}
              {intervention.solution?.alignment}
            </Pill>
            <small>
              {intervention.solution?.assessment}{" "}
              {intervention.solution?.origin === "fixture" ? "Fixed fixture review" : "Independent AI review"} of the
              proposal against the validated diagnosis. Not a human approval, and not training alignment.
            </small>
          </>
        ) : (
          <>
            <Pill tone="neutral">{intervention.state === "proposed" ? "Awaiting validation" : "Not applicable yet"}</Pill>
            <small>Runs once an intervention is proposed. Human approval of the diagnosis is not solution validation.</small>
          </>
        )}
      </div>
      <div className="insight-field" role="listitem">
        <span className="field-label">Training package</span>
        <Pill tone={trainingTone.tone}>{trainingTone.text}</Pill>
        {training.state === "generated" ? (
          <small>
            <b>{training.targetBehaviors[0]}</b> {training.outlineSectionCount} outline section
            {training.outlineSectionCount === 1 ? "" : "s"} · {training.activityCount} activit
            {training.activityCount === 1 ? "y" : "ies"} · {training.knowledgeCheckCount} knowledge check
            {training.knowledgeCheckCount === 1 ? "" : "s"} · {training.practiceScenarioCount} practice scenario
            {training.practiceScenarioCount === 1 ? "" : "s"} · {training.plannedMinutes} min planned
            {training.missingOperationalDetailCount > 0
              ? ` · ${training.missingOperationalDetailCount} operational detail${training.missingOperationalDetailCount === 1 ? "" : "s"} still needed`
              : ""}
            . <Link href={training.trainingHref}>Open training package</Link> ·{" "}
            <Link href={training.rolePlayHref}>Open role-play script</Link>
          </small>
        ) : (
          <small>{training.reason}</small>
        )}
      </div>
      <div className="insight-field" role="listitem">
        <span className="field-label">Alignment review</span>
        <Pill tone={alignmentTone.tone}>{alignmentTone.text}</Pill>
        {alignment.state === "design_aligned" || alignment.state === "design_questioned" ? (
          <small>
            <b>{alignment.assessment}</b> {alignmentFlagSummary(alignment)}.{" "}
            {alignment.origin === "fixture" ? "Fixture confidence value" : "Validator-reported confidence"}{" "}
            {alignment.confidence.value}; {alignment.confidence.wording}{" "}
            {alignment.origin === "fixture" ? "Fixed fixture review" : "Independent AI semantic review"} of the package
            against the confirmed gap. Not a human decision, not deployment, and not an outcome.
          </small>
        ) : (
          <small>{alignment.reason}</small>
        )}
      </div>
      <div className="insight-field" role="listitem">
        <span className="field-label">Outcome</span>
        <Pill tone="pending">Measurement pending</Pill>
        <small>
          {outcome.reason} <Link href="/kpi-tracker">Open KPI Tracker</Link>
        </small>
      </div>
    </div>
  );
}

function SelectedInsightCard({
  model,
  controls,
}: {
  model: HomeReadModel;
  controls?: ValidationControls;
}) {
  const insight = model.priority;
  if (!insight) {
    return (
      <section className="home-card insight-card" aria-labelledby="priority-title">
        <div className="insight-head neutral">
          <span className="badge">Selected insight</span>
          <h2 id="priority-title">No observed criteria yet</h2>
          <p className="insight-sub">
            Load QA evaluations to see an observed criterion here. Agent Insights remains available for detailed
            analysis.
          </p>
        </div>
        <div className="insight-actions">
          <Link className="button secondary" href={AGENT_INSIGHTS_PATH}>
            Open Agent Insights
          </Link>
        </div>
      </section>
    );
  }
  const { diagnosis, evidenceReview, humanValidation, failure } = insight;
  const evidencePill = evidenceReviewPill(evidenceReview);
  const headTone =
    humanValidation.state === "rejected"
      ? "rejected"
      : humanValidation.state === "approved" || humanValidation.state === "revised_approved"
        ? "validated"
        : diagnosis.state === "proposed"
          ? "attention"
          : "neutral";
  return (
    <section className="home-card insight-card" aria-labelledby="priority-title">
      <div className={`insight-head ${headTone}`}>
        <div className="insight-badges">
          <span className="badge">Selected insight</span>
          <span className="domain-tag">{insight.domain}</span>
          <span className="badge quiet">
            {diagnosis.state !== "proposed"
              ? "Observed only · no diagnosis yet"
              : diagnosis.humanRevised
                ? "Human-revised diagnosis"
                : diagnosis.origin === "fixture"
                  ? "Controlled non-AI fixture proposal"
                  : "AI proposal"}
          </span>
        </div>
        <h2 id="priority-title">{insight.criterion}</h2>
        <p className="insight-sub">
          <b>
            {failure.failCount} of {failure.evaluatedResults}
          </b>{" "}
          criterion results failed ({failure.failRateLabel} observed failure rate) · {failure.coverage.evaluated} of{" "}
          {failure.coverage.total} loaded evaluations contain this criterion
        </p>
      </div>

      <Pipeline insight={insight} />

      {diagnosis.state === "proposed" ? (
        <div className="insight-trio">
          <div className="insight-field">
            <span className="field-label">Working root cause</span>
            <strong>{diagnosis.causeDomain}</strong>
            <small>{diagnosis.observedDefect}</small>
            <small className="quiet">Working diagnosis · a cause type does not select training.</small>
          </div>
          <div className="insight-field split">
            <div>
              <span className="field-label">
                {diagnosis.origin === "fixture" ? "Fixture confidence value" : "Model-reported confidence"}
              </span>
              <strong>{diagnosis.confidence.value}</strong>
              <small>{diagnosis.confidence.wording}</small>
            </div>
            <div>
              <span className="field-label">Performance dimension</span>
              <strong>{diagnosis.performanceDimension}</strong>
              <small>Type of the working diagnosis. Not an intervention decision.</small>
            </div>
          </div>
          <div className="insight-field">
            <span className="field-label">Explanation</span>
            <p className="insight-explanation-text">{diagnosis.explanation}</p>
          </div>
        </div>
      ) : (
        <div className="insight-trio empty">
          <div className="insight-field">
            <span className="field-label">Working diagnosis</span>
            <strong className="muted">No diagnosis requested</strong>
            <small>
              The evidence is observed; no cause has been proposed. Request a hypothesis in Agent Insights.
            </small>
          </div>
        </div>
      )}

      <div className="review-split">
        <div className={`review-block ai ${evidenceReview.state}`}>
          <div className="review-block-head">
            <span className="field-label">AI evidence review</span>
            <Pill tone={evidencePill.tone}>{evidencePill.text}</Pill>
          </div>
          {evidenceReview.state === "evidence_validated" || evidenceReview.state === "evidence_questioned" ? (
            <>
              <p className="review-summary">{evidenceReview.assessment}</p>
              <small>
                {evidenceReview.unsupportedClaims} claim{evidenceReview.unsupportedClaims === 1 ? "" : "s"} beyond the
                evidence · {evidenceReview.missingEvidence} evidence gap{evidenceReview.missingEvidence === 1 ? "" : "s"}{" "}
                noted. Semantic review of the original proposal. Not a human decision or a review of any later human
                revision.
              </small>
            </>
          ) : (
            <small>
              {evidenceReview.state === "not_run"
                ? "Semantic evidence review has not been run for this proposal. It can be run in Agent Insights."
                : "Runs once a diagnosis exists."}
            </small>
          )}
        </div>
        <HumanValidationPanel
          key={`${insight.signalId}:${controls?.record?.provider_hypothesis.hypothesis_id ?? "none"}:${humanValidation.state}`}
          insight={insight}
          controls={controls}
        />
      </div>
      <p className="review-principle">AI checks the evidence. A human makes the consequential decision.</p>

      <DownstreamRows insight={insight} />

      <div className="insight-actions">
        <Link className="button primary" href={insight.reviewHref}>
          View full evidence in Agent Insights
        </Link>
        <div className="next-step">
          <span className="field-label">Recommended next step</span>
          <Link href={insight.nextStep.href}>{insight.nextStep.label}</Link>
          <small>{insight.nextStep.detail}</small>
        </div>
      </div>
    </section>
  );
}

/**
 * Evidence the Home read-model already exposes: observed counts and the citations of the
 * working diagnosis. Row text (evaluator feedback) is inspected in Agent Insights only.
 */
function EvidencePanel({ model }: { model: HomeReadModel }) {
  const insight = model.priority;
  return (
    <section className="home-card evidence-card" aria-labelledby="evidence-title">
      <div className="home-card-head">
        <div>
          <h2 id="evidence-title">Evidence from QA</h2>
          <p className="card-sub">Observed counts and cited references</p>
        </div>
        {insight && (
          <Link className="text-link" href={insight.reviewHref}>
            View all ↗
          </Link>
        )}
      </div>
      {!insight ? (
        <p className="quiet">Evidence appears once QA signals are loaded.</p>
      ) : (
        <>
          <ul className="evidence-facts">
            <li>
              <b>{insight.failure.failCount}</b> of {insight.failure.evaluatedResults} criterion results failed
            </li>
            <li>
              <b>{insight.failure.coverage.evaluated}</b> of {insight.failure.coverage.total} loaded evaluations contain
              this criterion
            </li>
            <li>
              <b>{insight.failure.feedbackCount}</b> rows carry evaluator feedback
            </li>
          </ul>
          {insight.evidence ? (
            <div className="cite-groups">
              <div className="cite-group supporting">
                <h3>
                  Supporting citations <b>{insight.evidence.supporting.length}</b>
                </h3>
                {insight.evidence.supporting.length ? (
                  <ul>
                    {insight.evidence.supporting.map((reference) => (
                      <li key={reference.item_id}>{referenceName(reference)}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="quiet">None cited.</p>
                )}
              </div>
              <div className="cite-group conflicting">
                <h3>
                  Conflicting citations <b>{insight.evidence.conflicting.length}</b>
                </h3>
                {insight.evidence.conflicting.length ? (
                  <ul>
                    {insight.evidence.conflicting.map((reference) => (
                      <li key={reference.item_id}>{referenceName(reference)}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="quiet">None cited.</p>
                )}
              </div>
              <div className="cite-group missing">
                <h3>
                  Missing evidence <b>{insight.evidence.missing.length}</b>
                </h3>
                {insight.evidence.missing.length ? (
                  <ul>
                    {insight.evidence.missing.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="quiet">None recorded.</p>
                )}
              </div>
            </div>
          ) : (
            <p className="quiet">Citations appear once a diagnosis exists.</p>
          )}
          <p className="privacy-note">
            Home shows references only. Evaluator feedback text is inspected row by row in Agent Insights.
          </p>
        </>
      )}
    </section>
  );
}

const greetingFor = (hour: number) =>
  hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

/** Pure view: renders a typed read-model with no data fetching, so tests drive it directly. */
export function CommandCenterView({
  model,
  greeting = "Hello",
  onRefresh,
  refreshing = false,
  onSelectSignal,
  controls,
  switching = false,
}: {
  model: HomeReadModel;
  greeting?: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  onSelectSignal?: (signalId: string) => void;
  controls?: ValidationControls;
  switching?: boolean;
}) {
  return (
    <main className="workspace home" aria-labelledby="home-title">
      <div className="workspace-heading home-head">
        <div>
          <span className="eyebrow">Command center</span>
          <h1 id="home-title">{greeting}. Here&apos;s what needs attention.</h1>
          <p>
            Observed QA criteria, the working diagnosis under review, and where each insight stands. Home summarizes;
            Agent Insights explains.
          </p>
        </div>
        <div className="home-heading-side">
          <ProvenanceBadge model={model} />
          {onRefresh && (
            <button type="button" className="button secondary" onClick={onRefresh} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          )}
        </div>
      </div>

      {model.requested && !model.requested.found && model.priority && (
        <p role="status" className="banner">
          Requested signal is unavailable. Showing the backend&apos;s first observed criterion instead.
        </p>
      )}

      <section className="summary-grid" aria-labelledby="summary-title">
        <h2 id="summary-title" className="visually-hidden">
          Top summary
        </h2>
        {model.summary.map((metric) => (
          <StatTile key={metric.id} metric={metric} />
        ))}
      </section>

      <div className="home-grid">
        <PerformanceGaps model={model} onSelectSignal={onSelectSignal} disabled={switching} />
        <SelectedInsightCard model={model} controls={controls} />
        <EvidencePanel model={model} />
      </div>
    </main>
  );
}

export default function CommandCenter({ initialSignalId = null }: { initialSignalId?: string | null } = {}) {
  const [sources, setSources] = useState<HomeSources | null>(null);
  const [model, setModel] = useState<HomeReadModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const selectedRef = useRef<string | null>(initialSignalId);
  const busyRef = useRef(false);
  const requestNumber = useRef(0);

  const load = useCallback(async (signalId: string | null) => {
    const request = ++requestNumber.current;
    selectedRef.current = signalId;
    setLoading(true);
    setError(null);
    try {
      const loaded = await loadHomeSources(signalId);
      if (request !== requestNumber.current) return;
      selectedRef.current = loaded.priority?.signal.signal_id ?? null;
      setSources(loaded);
      setModel(buildHomeReadModel(loaded));
    } catch (cause) {
      if (request === requestNumber.current) setError((cause as Error).message);
    } finally {
      if (request === requestNumber.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(() => load(initialSignalId));
  }, [load, initialSignalId]);

  const record =
    sources?.priority?.record && sources.priority.record.provider_hypothesis.signal_id === sources.priority.signal.signal_id
      ? sources.priority.record
      : null;

  async function decide(decision: ValidationDecision) {
    if (!record || busyRef.current || loading ||
        selectedRef.current !== record.provider_hypothesis.signal_id ||
        model?.priority?.signalId !== record.provider_hypothesis.signal_id) return;
    // Ignore double clicks and decisions from a record that is no longer selected.
    const id = record.provider_hypothesis.hypothesis_id;
    const signalId = selectedRef.current;
    busyRef.current = true;
    setBusy(true);
    setDecisionError(null);
    try {
      const body =
        decision.kind === "revise"
          ? { reviewer_id: decision.reviewer, rationale: decision.rationale, revision: decision.revision }
          : decision.kind === "reject"
            ? { reviewer_id: decision.reviewer, rationale: decision.rationale }
            : { reviewer_id: decision.reviewer };
      await api(`/hypotheses/${encodeURIComponent(id)}/${decision.kind}`, isRecordState, {
        method: "POST",
        body: JSON.stringify(body),
      });
      // The backend is the source of truth for every later stage: reload rather than patch.
      await load(signalId);
    } catch (cause) {
      setDecisionError((cause as Error).message);
      if (cause instanceof ApiError && cause.status === 409) await load(signalId);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  const loadBundle = (signalId: string) => api(`/signals/${encodeURIComponent(signalId)}/review-evidence`, isEvidenceBundle);

  if (loading && !model) {
    return (
      <main className="workspace home" aria-labelledby="home-title">
        <div className="workspace-heading home-head">
          <div>
            <span className="eyebrow">Command center</span>
            <h1 id="home-title">Here&apos;s what needs attention.</h1>
            <p role="status">Loading team summary from the diagnostic service…</p>
          </div>
        </div>
        <div className="summary-grid" aria-hidden="true">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="stat-tile skeleton" />
          ))}
        </div>
      </main>
    );
  }
  if (error && !model) {
    return (
      <main className="workspace home" aria-labelledby="home-title">
        <div className="workspace-heading home-head">
          <div>
            <span className="eyebrow">Command center</span>
            <h1 id="home-title">Here&apos;s what needs attention.</h1>
          </div>
        </div>
        <div role="alert" className="home-card home-error">
          <h2>Team summary unavailable</h2>
          <p>{error}</p>
          <div className="insight-actions">
            <button type="button" className="button primary" onClick={() => void load(selectedRef.current)}>
              Retry
            </button>
            <Link className="button secondary" href={AGENT_INSIGHTS_PATH}>
              Open Agent Insights
            </Link>
          </div>
        </div>
      </main>
    );
  }
  return (
    <>
      {error && (
        <div role="alert" className="banner error">
          <strong>Refresh failed</strong>
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">
            ×
          </button>
        </div>
      )}
      <CommandCenterView
        model={model!}
        greeting={greetingFor(new Date().getHours())}
        onRefresh={() => { if (!busyRef.current) void load(selectedRef.current); }}
        refreshing={loading || busy}
        onSelectSignal={(signalId) => {
          if (busyRef.current || loading || signalId === model?.priority?.signalId) return;
          setDecisionError(null);
          setSources(null);
          setModel(null);
          void load(signalId);
        }}
        switching={loading || busy}
        controls={{
          record,
          busy: busy || loading,
          error: decisionError,
          onDecide: (decision) => void decide(decision),
          loadBundle,
          reviewer,
          onReviewerChange: setReviewer,
        }}
      />
    </>
  );
}
