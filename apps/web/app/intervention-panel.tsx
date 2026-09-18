import { EvidenceGroup } from "./evidence-links";
import { label, type EvidenceReference } from "../lib/diagnostics";
import { gateText, type InterventionRecord } from "../lib/interventions";

const REVIEW_STATUS: Record<InterventionRecord["evidence_review_status"], string> = {
  evidence_validated: "evidence validated",
  evidence_questioned: "evidence questioned",
  not_reviewed: "no semantic evidence review recorded",
  original_proposal_only: "semantic review covered the original proposal only, not this revision",
};

function Items({ heading, items }: { heading: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div className="missing">
      <h4>{heading}</h4>
      <ul>
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Confidence({ value, fixture, who }: { value: number; fixture: boolean; who: string }) {
  return (
    <div className="confidence">
      <div>
        <span className="field-label">{fixture ? "Fixture confidence value" : `${who}-reported confidence`}</span>
        <strong>{value}</strong>
      </div>
      <p>
        {fixture ? "Fixed synthetic fixture value. No model reported it." : `Self-report by the ${who.toLowerCase()} for this output.`}{" "}
        It is not a statistically calibrated probability.
      </p>
    </div>
  );
}

/**
 * Stages 04 and 05 of the review workspace. Both are AI (or fixture) outputs about the
 * human-validated diagnosis; neither is a human decision, and neither changes the diagnosis.
 */
export default function InterventionPanel({
  record,
  humanRevised,
  busy,
  onPropose,
  onValidate,
  onSelect,
}: {
  record: InterventionRecord | null;
  humanRevised: boolean;
  busy: boolean;
  onPropose: () => void;
  onValidate: () => void;
  onSelect: (reference: EvidenceReference) => void;
}) {
  const proposal = record?.proposal ?? null;
  const fixture = proposal?.provider_metadata.generation_mode === "controlled_fixture";
  const review = record?.solution_validation ?? null;
  const reviewFixture = review?.provider_metadata.generation_mode === "controlled_fixture";
  const questioned = review?.solution_status === "solution_questioned";
  return (
    <>
      <section className="validation intervention-stage" aria-label="Proposed intervention">
        <div className="section-kicker">
          <span className="level-dot intervention-dot" /> 04 / INTERVENTION PROPOSED
        </div>
        <h2>What should ResultsCX actually do?</h2>
        {!proposal || !record ? (
          <>
            <p>
              Ask the intervention reasoner what to do about the human-validated diagnosis. Training is one option beside practice,
              coaching, process correction, and further investigation. A performance problem does not automatically call for training,
              and training has not yet been selected.
            </p>
            <button type="button" className="button primary" disabled={busy} onClick={onPropose}>
              Propose intervention
            </button>
          </>
        ) : (
          <>
            <div className="working-diagnosis intervention-verdict">
              <strong>{label(proposal.intervention_type)}</strong>
              <span>INTERVENTION PROPOSED · NOT HUMAN VALIDATED</span>
              <small>
                {fixture ? "Fixed fixture proposal" : "AI proposal"} for the{" "}
                {record.validated_diagnosis.human_revised ? "human-revised" : "reviewer-accepted"} diagnosis{" "}
                {label(record.validated_diagnosis.diagnosis.cause_domain)} · {label(record.validated_diagnosis.diagnosis.performance_dimension)}.
                Supervisor {record.validated_diagnosis.approved_by} approved it with evidence review status: {REVIEW_STATUS[record.evidence_review_status]}.
              </small>
            </div>
            <p className="intervention-recommendation">{proposal.recommendation}</p>
            <div className="reasoning">
              <span className="field-label">Intervention rationale</span>
              <p>{proposal.rationale}</p>
            </div>
            <div className="reasoning">
              <span className="field-label">Target behavior or operational change</span>
              <p>{proposal.target_change}</p>
            </div>
            <div className="reasoning">
              <span className="field-label">Why this fits the validated cause</span>
              <p>{proposal.fit_to_cause}</p>
            </div>
            <div className="evidence-pair">
              <EvidenceGroup
                title="Evidence the intervention cites"
                references={proposal.evidence_refs}
                kind="supporting"
                onSelect={onSelect}
                emptyText="No evidence cited."
              />
            </div>
            <Items heading="Limitations" items={proposal.limitations} />
            <Items heading="Evidence still needed" items={proposal.missing_evidence} />
            <Confidence value={proposal.provider_reported_confidence} fixture={fixture} who="Reasoner" />
            <div className="provider-meta">
              Provider: {proposal.provider_metadata.provider}
              {proposal.provider_metadata.model ? ` · ${proposal.provider_metadata.model}` : ""}
            </div>
            <p>This proposal is not a decision. It does not change the diagnosis and has not been human validated.</p>
          </>
        )}
      </section>
      <section className="validation solution-stage" aria-label="Solution validation">
        <div className="section-kicker">
          <span className="level-dot solution-dot" /> 05 / SOLUTION VALIDATION
        </div>
        <h2>Does the proposed intervention address the validated diagnosis?</h2>
        {!record ? (
          <p>Available once an intervention has been proposed.</p>
        ) : !review ? (
          <>
            <p>
              Ask the solution validator whether the proposal logically addresses the {humanRevised ? "human-revised" : "human-validated"}{" "}
              cause and the observed problem. It cannot change the diagnosis, and its answer is not human approval of the intervention.
            </p>
            <button type="button" className="button secondary" disabled={busy} onClick={onValidate}>
              Validate solution
            </button>
          </>
        ) : (
          <>
            <div className={`working-diagnosis solution-verdict ${questioned ? "questioned" : ""}`}>
              <strong>{label(review.alignment_outcome)}</strong>
              <span>{questioned ? "SOLUTION QUESTIONED" : "SOLUTION VALIDATED"}</span>
              <small>
                {reviewFixture ? "Fixed fixture review" : "Independent AI review"} of the proposal against the human-validated
                diagnosis. Not a human decision, and not approval of training.
              </small>
            </div>
            <p>{review.alignment_assessment}</p>
            <Items heading="What is aligned" items={review.aligned_points} />
            <Items heading="What is not aligned" items={review.misaligned_points} />
            <Items heading="Unsupported solution assumptions" items={review.unsupported_assumptions} />
            <Items heading="Missing information" items={review.missing_information} />
            <Confidence value={review.provider_reported_confidence} fixture={reviewFixture} who="Validator" />
            <div className="provider-meta">
              Provider: {review.provider_metadata.provider}
              {review.provider_metadata.model ? ` · ${review.provider_metadata.model}` : ""}
            </div>
            <p className={`handoff-note ${record.handoff.training_design_gate}`} role="note">
              {gateText(record.handoff.training_design_gate, record.proposal.intervention_type)}
            </p>
          </>
        )}
      </section>
    </>
  );
}
