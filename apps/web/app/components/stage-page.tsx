"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { AGENT_INSIGHTS_PATH, type HomeReadModel, type PriorityInsight } from "../../lib/home/read-model";
import { interventionPill, Pill, Pipeline, trainingPill } from "../command-center";
import type { InsightLoad } from "./use-insight-sources";

/**
 * Shared frame for the pages that display one signal's downstream artifacts. It owns the
 * loading, error, empty, and unknown-signal states so Training, Role-Play, and KPI Tracker
 * render only their own content.
 */
export function StagePage({
  eyebrow,
  title,
  lead,
  load,
  children,
}: {
  eyebrow: string;
  title: string;
  lead: string;
  load: InsightLoad;
  children: (model: HomeReadModel) => ReactNode;
}) {
  const { model, error, loading, reload } = load;
  return (
    <main className="workspace stage-page" aria-labelledby="stage-title">
      <div className="workspace-heading">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h1 id="stage-title">{title}</h1>
          <p>{lead}</p>
        </div>
        {model && !loading && (
          <button type="button" className="button secondary" onClick={reload}>
            Refresh
          </button>
        )}
      </div>
      {loading && !model ? (
        <p role="status" className="state-copy">
          Loading from the diagnostic service…
        </p>
      ) : error && !model ? (
        <div role="alert" className="home-card home-error">
          <h2>Unavailable</h2>
          <p>{error}</p>
          <div className="insight-actions">
            <button type="button" className="button primary" onClick={reload}>
              Retry
            </button>
            <Link className="button secondary" href="/">
              Back to Home
            </Link>
          </div>
        </div>
      ) : model ? (
        <>
          {error && (
            <div role="alert" className="banner error">
              <strong>Refresh failed</strong>
              <span>{error}</span>
            </div>
          )}
          {model.requested && !model.requested.found && model.priority && (
            <p role="status" className="banner">
              Requested signal is unavailable. Showing the backend&apos;s first observed criterion instead.
            </p>
          )}
          {children(model)}
        </>
      ) : null}
    </main>
  );
}

/** The validated diagnosis and the AWS-4 decision a package was, or was not, built from. */
export function InterventionContext({ insight }: { insight: PriorityInsight }) {
  const { diagnosis, humanValidation, intervention, training } = insight;
  const interventionTone = interventionPill(intervention);
  const trainingTone = trainingPill(training);
  const proposed =
    intervention.state === "proposed" ||
    intervention.state === "solution_validated" ||
    intervention.state === "solution_questioned";
  return (
    <section className="home-card stage-context" aria-labelledby="context-title">
      <div className="home-card-head">
        <div>
          <span className="eyebrow">{insight.domain} · selected insight</span>
          <h2 id="context-title">{insight.criterion}</h2>
        </div>
        <div className="observed-rate">
          <strong>{insight.failure.failRateLabel}</strong>
          <span>observed failure rate</span>
        </div>
      </div>
      <Pipeline insight={insight} />
      <div className="insight-grid">
        <div className="insight-field">
          <span className="field-label">Diagnosis and human review</span>
          {diagnosis.state === "proposed" ? (
            <>
              <strong>{diagnosis.observedDefect}</strong>
              <small>
                {diagnosis.causeDomain} · {diagnosis.performanceDimension} ·{" "}
                {humanValidation.state === "approved" || humanValidation.state === "revised_approved"
                  ? `human validated${humanValidation.reviewer ? ` by ${humanValidation.reviewer}` : ""}`
                  : "not yet human validated"}
              </small>
            </>
          ) : (
            <>
              <strong className="muted">No diagnosis requested</strong>
              <small>The evidence is observed; no cause has been proposed.</small>
            </>
          )}
        </div>
        <div className="insight-field">
          <span className="field-label">Intervention and solution</span>
          <Pill tone={interventionTone.tone}>{interventionTone.text}</Pill>
          {proposed ? (
            <>
              <strong>{intervention.recommendation}</strong>
              <small>Target change: {intervention.targetChange}</small>
              {intervention.solution && <small>Solution review: {intervention.solution.assessment}</small>}
            </>
          ) : (
            <small>No intervention has been proposed for this diagnosis.</small>
          )}
        </div>
        <div className="insight-field">
          <span className="field-label">Training design</span>
          <Pill tone={trainingTone.tone}>{trainingTone.text}</Pill>
          <small>
            {training.state === "generated"
              ? `Design status: ${training.designStatus.replaceAll("_", " ")}. ${training.origin === "fixture" ? "Controlled non-AI fixture package." : "AI-generated package."} Generated, not deployed; no learner has taken it.`
              : training.reason}
          </small>
        </div>
        <div className="insight-field">
          <span className="field-label">Alignment review</span>
          <Pill tone={insight.alignment.state === "pending" ? "pending" : insight.alignment.state === "not_applicable" ? "not_applicable" : "neutral"}>
            {insight.alignment.state === "pending"
              ? "Pending · not yet reviewed"
              : insight.alignment.state === "not_applicable"
                ? "Not applicable"
                : "Blocked upstream"}
          </Pill>
          <small>{insight.alignment.reason}</small>
        </div>
      </div>
      <div className="insight-actions">
        <Link className="button secondary" href={insight.reviewHref}>
          Open in Agent Insights
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

/** Explicit state for a page whose artifact does not exist yet. No controls, no figures. */
export function StageUnavailable({
  title,
  detail,
  insight,
}: {
  title: string;
  detail: string;
  insight: PriorityInsight | null;
}) {
  return (
    <section className="home-card stage-empty" aria-labelledby="stage-empty-title">
      <h2 id="stage-empty-title">{title}</h2>
      <p>{detail}</p>
      <div className="insight-actions">
        <Link className="button primary" href={insight?.reviewHref ?? AGENT_INSIGHTS_PATH}>
          Open Agent Insights
        </Link>
        <Link className="button secondary" href="/">
          Back to Home
        </Link>
      </div>
    </section>
  );
}
