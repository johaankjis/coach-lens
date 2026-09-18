import { label } from "../lib/diagnostics";
import { ALIGNMENT_DIMENSIONS, type AlignmentReview } from "../lib/designs";

const DIMENSION_TITLES: Record<(typeof ALIGNMENT_DIMENSIONS)[number], string> = {
  gap_to_target_behavior: "Confirmed gap → target behavior",
  target_behavior_to_objective: "Target behavior → objective",
  objective_to_activity: "Objective → activity",
  objective_to_knowledge_check: "Objective → knowledge check",
  target_behavior_to_practice: "Target behavior → practice",
  practice_to_rubric: "Practice → rubric",
  intervention_to_package: "Validated intervention → package",
};

/**
 * AWS-6 semantic alignment review of a stored AWS-5 package. It is an AI (or fixture)
 * judgement about meaning, not a human decision and not the AWS-5 structural trace. It never
 * edits the package and never claims the training was delivered or effective.
 */
export default function AlignmentCheck({ review }: { review: AlignmentReview }) {
  const fixture = review.provider_metadata.generation_mode === "controlled_fixture";
  const questioned = review.design_status === "design_questioned";
  const shortId = (id: string) => (id.startsWith(`${review.run_id}/`) ? id.slice(review.run_id.length + 1) : id);
  return (
    <section className={`design-section alignment-check${questioned ? " questioned" : ""}`} aria-label="Alignment check">
      <span className="eyebrow">Alignment Check</span>
      <h3>AI semantic design review</h3>
      <p className="alignment-scope">
        Independent of the AWS-5 structural trace: the trace proved every reference exists and is consistent
        (<code>structural_references_only</code>); this review judges whether the meaning of each design element
        addresses the human-confirmed gap and the validated intervention. It changed nothing in the package.
      </p>
      <div className="alignment-status" role="status">
        {questioned ? "DESIGN QUESTIONED" : "DESIGN ALIGNED"} · {label(review.overall_outcome)}
      </div>
      <dl>
        <div>
          <dt>Assessment</dt>
          <dd>{review.overall_assessment}</dd>
        </div>
        <div>
          <dt>{fixture ? "Fixture confidence value" : "Validator-reported confidence"}</dt>
          <dd>
            <strong>{review.provider_reported_confidence}</strong>{" "}
            <span className="quiet">
              {fixture ? "Fixed synthetic fixture value. No model reported it." : "Self-report by the validator for this output."}{" "}
              It is not a statistically calibrated probability.
            </span>
          </dd>
        </div>
      </dl>
      <h4>Alignment dimensions</h4>
      <ul className="alignment-dimensions">
        {ALIGNMENT_DIMENSIONS.map((name) => {
          const dimension = review.dimensions[name];
          return (
            <li key={name} className={dimension.outcome === "aligned" || dimension.outcome === "not_applicable" ? "" : "flagged"}>
              <span className="dimension-outcome">{label(dimension.outcome)}</span>
              <strong>{DIMENSION_TITLES[name]}</strong>
              <p>{dimension.assessment}</p>
              {dimension.misaligned_element_ids.length > 0 && (
                <p className="quiet">Elements: {dimension.misaligned_element_ids.map(shortId).join(", ")}</p>
              )}
            </li>
          );
        })}
      </ul>
      <dl>
        <div>
          <dt>Problematic design elements</dt>
          <dd>{review.misaligned_element_ids.length > 0 ? review.misaligned_element_ids.map(shortId).join(", ") : "None named."}</dd>
        </div>
        <div>
          <dt>Unsupported assumptions</dt>
          <dd>
            {review.unsupported_assumptions.length > 0 ? (
              <ul>{review.unsupported_assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul>
            ) : "None named."}
          </dd>
        </div>
        <div>
          <dt>Missing information</dt>
          <dd>
            {review.missing_information.length > 0 ? (
              <ul>{review.missing_information.map((item, i) => <li key={i}>{item}</li>)}</ul>
            ) : "None named."}
          </dd>
        </div>
      </dl>
      <p className="quiet alignment-origin">
        Review origin: {fixture ? "Controlled non-AI fixture" : "AI semantic review"} ({review.provider_metadata.provider}
        {review.provider_metadata.model ? ` / ${review.provider_metadata.model}` : ""}) · review {review.alignment_review_id}.
        Not a human decision. Nothing has been deployed and no outcome has been measured.
      </p>
    </section>
  );
}
