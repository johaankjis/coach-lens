"use client";

import Link from "next/link";
import { label } from "../../lib/diagnostics";
import { agentInsightsHref, percentLabel } from "../../lib/home/read-model";
import { useInsightSources } from "../components/use-insight-sources";
import { StagePage } from "../components/stage-page";

/**
 * Outcome measurement is not implemented. This page states that explicitly and shows the
 * baseline that a later ResultsCX QA load would be compared against: the M2 observed counts
 * the backend already returns. Every figure is a backend value; nothing is projected.
 */
export default function OutcomeTracker() {
  const load = useInsightSources(null);
  return (
    <StagePage
      eyebrow="KPI Tracker · outcome measurement"
      title="Outcome measurement pending"
      lead="No post-intervention QA has been loaded, so no outcome can be measured and no improvement is shown. The observed baseline below is what a future ResultsCX QA load would be compared against, by deterministic code."
      load={load}
    >
      {(model) => {
        const signals = load.sources?.signals ?? [];
        const insight = model.priority;
        return (
          <>
            <section className="home-card outcome-status" aria-labelledby="outcome-title">
              <div className="home-card-head">
                <div>
                  <span className="eyebrow">Measurement status</span>
                  <h2 id="outcome-title">Nothing to compare yet</h2>
                </div>
              </div>
              <ul className="outcome-steps">
                <li>
                  <strong>Baseline established</strong>
                  <span>
                    {model.provenance.label}. {model.observedSignalCount} observed criteria with M2 failure counts.
                  </span>
                </li>
                <li>
                  <strong>Intervention state</strong>
                  <span>
                    {insight
                      ? insight.training.state === "generated"
                        ? "A training package is generated for the selected insight. It has not been delivered."
                        : insight.intervention.state === "solution_validated"
                          ? `${insight.intervention.typeLabel} was solution validated for the selected insight. Nothing has been deployed.`
                          : "No intervention has been solution validated for the selected insight."
                      : "No observed criteria are loaded."}
                  </span>
                </li>
                <li>
                  <strong>Post-intervention QA</strong>
                  <span>Pending. No follow-up evaluations have been loaded.</span>
                </li>
                <li>
                  <strong>Outcome comparison</strong>
                  <span>Pending. A comparison exists only when both loads exist; it will be computed by the backend, not this page.</span>
                </li>
              </ul>
            </section>
            <section className="home-card baseline" aria-labelledby="baseline-title">
              <div className="home-card-head">
                <div>
                  <span className="eyebrow">M2 observed baseline · backend order</span>
                  <h2 id="baseline-title">Observed criteria at baseline</h2>
                </div>
              </div>
              {signals.length === 0 ? (
                <div className="home-empty">
                  <p>No QA signals are loaded.</p>
                  <span>Load normalized evaluations in the API to establish a baseline.</span>
                </div>
              ) : (
                <table className="baseline-table">
                  <thead>
                    <tr>
                      <th scope="col">Criterion</th>
                      <th scope="col">Domain</th>
                      <th scope="col">Failed / evaluated</th>
                      <th scope="col">Observed failure rate</th>
                      <th scope="col">Post-intervention</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((signal) => (
                      <tr key={signal.signal_id}>
                        <th scope="row">
                          <Link href={agentInsightsHref(signal.signal_id)}>{signal.criterion}</Link>
                        </th>
                        <td>{label(signal.domain)}</td>
                        <td>
                          {signal.fail_count} / {signal.evaluated_results}
                        </td>
                        <td>{percentLabel(signal.fail_rate)}</td>
                        <td className="muted">Pending</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="source-note">
                Baseline figures are M2 calculations from the loaded evaluations. No improvement percentage exists and none is estimated.
              </p>
            </section>
          </>
        );
      }}
    </StagePage>
  );
}
