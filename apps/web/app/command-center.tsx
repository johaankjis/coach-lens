"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { shortId } from "../lib/diagnostics";
import { loadHomeReadModel } from "../lib/home/load";
import {
  AGENT_INSIGHTS_PATH,
  type DownstreamStage,
  type EvidenceReviewStatus,
  type HomeReadModel,
  type HumanValidationStatus,
  type PriorityInsight,
  type SummaryMetric,
} from "../lib/home/read-model";

/* ---------- Status vocabulary ----------------------------------------------------------
 * Tone classes are deliberately separate from meaning: semantic "questioned" is caution
 * (amber), never the red reserved for a human rejection. */
type Tone = "neutral" | "validated" | "caution" | "rejected" | "proposed" | "pending";

function Pill({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function evidenceReviewPill(status: EvidenceReviewStatus): { tone: Tone; text: string } {
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

function humanValidationPill(status: HumanValidationStatus): { tone: Tone; text: string } {
  const by = status.reviewer ? ` by ${status.reviewer}` : "";
  switch (status.state) {
    case "none":
      return { tone: "neutral", text: "No diagnosis to validate" };
    case "awaiting_review":
      return { tone: "neutral", text: "Awaiting human review" };
    case "approved":
      return { tone: "validated", text: `Approved${by}` };
    case "revised_pending":
      return { tone: "caution", text: "Revised · awaiting approval" };
    case "revised_approved":
      return { tone: "validated", text: `Revision approved${by}` };
    case "rejected":
      return { tone: "rejected", text: `Rejected${by}` };
  }
}

function downstreamPill(stage: DownstreamStage): { tone: Tone; text: string } {
  switch (stage.status) {
    case "pending_backend":
      return { tone: "pending", text: "Pending backend" };
    case "blocked":
      return { tone: "neutral", text: "Blocked upstream" };
    case "not_started":
      return { tone: "neutral", text: "Not started" };
    case "proposed":
      return { tone: "proposed", text: "Proposed · not validated" };
    case "not_applicable":
      return { tone: "neutral", text: "Not applicable" };
  }
}

/* ---------- Sections ------------------------------------------------------------------- */

function ProvenanceBadge({ model }: { model: HomeReadModel }) {
  const { provenance } = model;
  return (
    <div className={`provenance ${provenance.kind}`} role="note" aria-label="Data provenance">
      <strong>{provenance.label}</strong>
      <span>{provenance.detail}</span>
      <small>
        Diagnostic provider: {provenance.diagnosticProvider} · Design provider:{" "}
        {provenance.designProvider}
      </small>
    </div>
  );
}

function StatTile({ metric }: { metric: SummaryMetric }) {
  const { reading } = metric;
  return (
    <article className={`stat-tile ${reading.state}`} aria-labelledby={`stat-${metric.id}`}>
      <h3 id={`stat-${metric.id}`}>{metric.label}</h3>
      {reading.state === "available" ? (
        <>
          <p className="stat-value">{reading.value}</p>
          <p className="stat-detail">{reading.detail}</p>
        </>
      ) : (
        <>
          <p className="stat-value muted">{reading.state === "pending" ? "Pending" : "Unavailable"}</p>
          <p className="stat-detail">{reading.reason}</p>
          {reading.state === "pending" && reading.note && (
            <p className="stat-note">{reading.note}</p>
          )}
        </>
      )}
      <p className="stat-source">Source: {metric.source}</p>
    </article>
  );
}

function PerformanceGaps({ model }: { model: HomeReadModel }) {
  return (
    <section className="home-card gaps" aria-labelledby="gaps-title">
      <div className="home-card-head">
        <div>
          <span className="eyebrow">M2 observations · ordered by the backend</span>
          <h2 id="gaps-title">Observed QA criteria</h2>
        </div>
        {model.observedSignalCount > 0 && (
          <Link className="text-link" href={AGENT_INSIGHTS_PATH}>
            All {model.observedSignalCount} observed signals ↗
          </Link>
        )}
      </div>
      {model.gaps.length === 0 ? (
        <div className="home-empty">
          <p>No QA signals are loaded.</p>
          <span>Load normalized evaluations in the API to see observed criteria here.</span>
        </div>
      ) : (
        <ol className="gap-list">
          {model.gaps.map((gap) => (
            <li key={gap.signalId} className="gap-row">
              <span className="gap-rank" aria-hidden="true">
                {String(gap.rank).padStart(2, "0")}
              </span>
              <div className="gap-body">
                <div className="gap-title">
                  <span className="domain-tag">{gap.domain}</span>
                  <Link href={gap.href} className="gap-link">
                    {gap.criterion}
                  </Link>
                </div>
                <div
                  className="gap-bar"
                  role="img"
                  aria-label={`Observed failure rate ${gap.failRateLabel}`}
                >
                  <span style={{ width: `${Math.round(gap.failRateFraction * 100)}%` }} />
                </div>
                <div className="gap-meta">
                  <span>
                    <b>{gap.failRateLabel}</b> observed failure rate
                  </span>
                  <span>
                    {gap.failCount}/{gap.evaluatedResults} results failed
                  </span>
                  <span>
                    {gap.coverage.evaluated} of {gap.coverage.total} evaluations contain it
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="source-note">
        Ordered by failure count, then failure rate. Criteria with zero failures may appear.
        This order does not establish severity or cause.
      </p>
    </section>
  );
}

function Pipeline({ insight, downstream }: { insight: PriorityInsight; downstream: DownstreamStage[] }) {
  const evidence = evidenceReviewPill(insight.evidenceReview);
  const human = humanValidationPill(insight.humanValidation);
  const steps: { name: string; tone: Tone; text: string }[] = [
    { name: "Observed", tone: "validated", text: "Deterministic" },
    {
      name: "Working diagnosis",
      tone: insight.diagnosis.state === "proposed" ? "proposed" : "neutral",
      text: insight.diagnosis.state === "proposed" ? "Proposed" : "Not requested",
    },
    { name: "Evidence review", ...evidence },
    { name: "Human validation", ...human },
    ...downstream.map((stage) => ({ name: stage.label, ...downstreamPill(stage) })),
  ];
  return (
    <ol className="pipeline" aria-label="Progress of this insight through the workflow">
      {steps.map((step) => (
        <li key={step.name} className={`pipeline-step ${step.tone}`}>
          <span className="pipeline-name">{step.name}</span>
          <span className="pipeline-state">{step.text}</span>
        </li>
      ))}
    </ol>
  );
}

function PriorityInsightCard({ model }: { model: HomeReadModel }) {
  const insight = model.priority;
  if (!insight) {
    return (
      <section className="home-card priority" aria-labelledby="priority-title">
        <span className="eyebrow">Selected insight</span>
        <h2 id="priority-title">No observed criteria yet</h2>
        <p>
          Load QA evaluations to see an observed criterion here. Agent Insights remains available
          for detailed analysis.
        </p>
        <Link className="button secondary" href={AGENT_INSIGHTS_PATH}>
          Open Agent Insights
        </Link>
      </section>
    );
  }
  const { diagnosis, evidenceReview, humanValidation, failure, evidence } = insight;
  const evidencePill = evidenceReviewPill(evidenceReview);
  const humanPill = humanValidationPill(humanValidation);
  return (
    <section className="home-card priority" aria-labelledby="priority-title">
      <div className="home-card-head">
        <div>
          <span className="eyebrow">Selected insight · first in backend failure-count order</span>
          <h2 id="priority-title">{insight.criterion}</h2>
          <span className="domain-tag">{insight.domain}</span>
        </div>
        <div className="observed-rate">
          <strong>{failure.failRateLabel}</strong>
          <span>observed failure rate</span>
        </div>
      </div>

      <Pipeline insight={insight} downstream={model.downstream} />

      <div className="insight-grid">
        <div className="insight-field">
          <span className="field-label">Performance issue</span>
          <strong>
            {failure.failCount} of {failure.evaluatedResults} criterion results failed
          </strong>
          <small>
            {failure.coverage.evaluated} of {failure.coverage.total} loaded evaluations contain
            this criterion · {failure.feedbackCount} with evaluator feedback
          </small>
        </div>

        <div className="insight-field">
          <span className="field-label">Working diagnosis</span>
          {diagnosis.state === "proposed" ? (
            <>
              <strong>{diagnosis.observedDefect}</strong>
              <small>
                {diagnosis.humanRevised
                  ? "Human-revised working diagnosis"
                  : diagnosis.origin === "fixture"
                    ? "Controlled non-AI fixture proposal"
                    : "AI proposal"}{" "}
                · not yet an intervention decision
              </small>
            </>
          ) : (
            <>
              <strong>No diagnosis requested</strong>
              <small>The evidence is observed; no cause has been proposed.</small>
            </>
          )}
        </div>

        <div className="insight-field">
          <span className="field-label">Working cause type</span>
          {diagnosis.state === "proposed" ? (
            <>
              <strong>
                {diagnosis.causeDomain} · {diagnosis.performanceDimension}
              </strong>
              <small>A cause type describes the hypothesis. It does not select training.</small>
            </>
          ) : (
            <strong className="muted">Not proposed</strong>
          )}
        </div>

        <div className="insight-field">
          <span className="field-label">
            {diagnosis.state === "proposed" && diagnosis.origin === "fixture"
              ? "Fixture confidence value"
              : "Model-reported confidence"}
          </span>
          {diagnosis.state === "proposed" ? (
            <>
              <strong>{diagnosis.confidence.value}</strong>
              <small>{diagnosis.confidence.wording}</small>
            </>
          ) : (
            <strong className="muted">Not applicable</strong>
          )}
        </div>

        <div className="insight-field">
          <span className="field-label">Evidence review</span>
          <Pill tone={evidencePill.tone}>{evidencePill.text}</Pill>
          <small>
            {evidenceReview.state === "evidence_validated" ||
            evidenceReview.state === "evidence_questioned"
              ? "Semantic review of the original proposal. Not a human decision or a review of any later human revision."
              : evidenceReview.state === "not_run"
                ? "Semantic evidence review has not been run for this proposal."
                : "Runs once a diagnosis exists."}
          </small>
        </div>

        <div className="insight-field">
          <span className="field-label">Human validation</span>
          <Pill tone={humanPill.tone}>{humanPill.text}</Pill>
          <small>
            {humanValidation.state === "rejected" && humanValidation.rationale
              ? humanValidation.rationale
              : humanValidation.state === "approved" || humanValidation.state === "revised_approved"
                ? "Approval records a human decision, not objective causal truth."
                : "A human reviewer approves, revises, or rejects in Agent Insights."}
          </small>
        </div>
      </div>

      {diagnosis.state === "proposed" && (
        <div className="insight-explanation">
          <span className="field-label">Explanation</span>
          <p>{diagnosis.explanation}</p>
        </div>
      )}

      {evidenceReview.state === "evidence_validated" || evidenceReview.state === "evidence_questioned" ? (
        <div className={`insight-explanation semantic ${evidenceReview.state}`}>
          <span className="field-label">Semantic evidence assessment</span>
          <p>{evidenceReview.assessment}</p>
          <small>
            {evidenceReview.unsupportedClaims} claim
            {evidenceReview.unsupportedClaims === 1 ? "" : "s"} beyond the evidence ·{" "}
            {evidenceReview.missingEvidence} evidence gap
            {evidenceReview.missingEvidence === 1 ? "" : "s"} noted
          </small>
        </div>
      ) : null}

      <section className="evidence-preview" aria-label="Evidence preview">
        <h3 className="field-label">Evidence preview</h3>
        {evidence ? (
          <div className="evidence-preview-grid">
            <div>
              <b>{evidence.supporting.length}</b> supporting
              <ul>
                {evidence.supporting.slice(0, 3).map((reference) => (
                  <li key={reference.item_id}>
                    {reference.item_id === "signal"
                      ? "Aggregate QA signal"
                      : `Evaluation ${shortId(reference.evaluation_id ?? "")}`}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <b>{evidence.conflicting.length}</b> conflicting
              <ul>
                {evidence.conflicting.slice(0, 3).map((reference) => (
                  <li key={reference.item_id}>
                    {reference.item_id === "signal"
                      ? "Aggregate QA signal"
                      : `Evaluation ${shortId(reference.evaluation_id ?? "")}`}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <b>{evidence.missing.length}</b> missing
              <ul>
                {evidence.missing.slice(0, 2).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          <p className="quiet">
            Citations appear once a diagnosis exists. Source QA rows are inspected in Agent
            Insights.
          </p>
        )}
      </section>

      <div className="insight-actions">
        <Link className="button primary" href={insight.reviewHref}>
          Continue in Agent Insights
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

function Downstream({ model }: { model: HomeReadModel }) {
  return (
    <section className="home-card downstream" aria-labelledby="downstream-title">
      <div className="home-card-head">
        <div>
          <span className="eyebrow">After human validation</span>
          <h2 id="downstream-title">Intervention, training, alignment, outcome</h2>
        </div>
      </div>
      <ul className="downstream-grid">
        {model.downstream.map((stage) => {
          const pill = downstreamPill(stage);
          return (
            <li key={stage.id} className={`downstream-card ${stage.status}`}>
              <h3>{stage.label}</h3>
              <Pill tone={pill.tone}>{pill.text}</Pill>
              <p>{stage.detail}</p>
              <small>Source: {stage.source}</small>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Pure view: renders a typed read-model with no data fetching, so tests drive it directly. */
export function CommandCenterView({
  model,
  onRefresh,
  refreshing = false,
}: {
  model: HomeReadModel;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  return (
    <main className="workspace home" aria-labelledby="home-title">
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">Command center</span>
          <h1 id="home-title">What needs attention across the team?</h1>
          <p>
            Observed QA criteria, the working diagnosis under review, and where to go next. Home
            summarizes; Agent Insights explains.
          </p>
        </div>
        <div className="home-heading-side">
          <ProvenanceBadge model={model} />
          {onRefresh && (
            <button
              type="button"
              className="button secondary"
              onClick={onRefresh}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          )}
        </div>
      </div>

      <section className="summary-grid" aria-labelledby="summary-title">
        <h2 id="summary-title" className="visually-hidden">
          Top summary
        </h2>
        {model.summary.map((metric) => (
          <StatTile key={metric.id} metric={metric} />
        ))}
      </section>

      <div className="home-grid">
        <PriorityInsightCard model={model} />
        <PerformanceGaps model={model} />
      </div>

      <Downstream model={model} />
    </main>
  );
}

export default function CommandCenter() {
  const [model, setModel] = useState<HomeReadModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setModel(await loadHomeReadModel());
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);

  if (loading && !model) {
    return (
      <main className="workspace home" aria-labelledby="home-title">
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">Command center</span>
            <h1 id="home-title">What needs attention across the team?</h1>
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
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">Command center</span>
            <h1 id="home-title">What needs attention across the team?</h1>
          </div>
        </div>
        <div role="alert" className="home-card home-error">
          <h2>Team summary unavailable</h2>
          <p>{error}</p>
          <div className="insight-actions">
            <button type="button" className="button primary" onClick={() => void load()}>
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
      <CommandCenterView model={model!} onRefresh={() => void load()} refreshing={loading} />
    </>
  );
}
