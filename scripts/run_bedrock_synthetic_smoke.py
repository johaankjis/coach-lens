"""Invoke AWS-1, AWS-3, AWS-4, and AWS-5 with synthetic QA only. Uses the normal AWS credential chain.

After the AWS-3 review the script records a synthetic human approval (reviewer "smoke") so the
AWS-4 Intervention Reasoner and Solution Validator can run on the approved diagnosis. It then
runs the real M5 design service with the AWS-4 handoff: the AWS-5 Bedrock Training Designer
is invoked only if the live reasoner proposed a training or practice intervention that the
live solution review found aligned; otherwise the run reports the withheld or non-training
outcome. Pass `--skip-intervention` to stop after AWS-3, or `--skip-design` after AWS-4.
"""

import argparse

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.design.bedrock import BedrockTrainingDesigner  # noqa: E402
from app.design.service import DesignError, DesignService  # noqa: E402
from app.diagnostics.bedrock import BedrockReasoner  # noqa: E402
from app.diagnostics.engine import DiagnosticService  # noqa: E402
from app.diagnostics.engine import ProviderOutputError  # noqa: E402
from app.diagnostics.evidence_validator import BedrockEvidenceValidator, EvidenceValidationService  # noqa: E402
from app.interventions.bedrock import (BedrockInterventionReasoner, BedrockSolutionValidator,  # noqa: E402
                                       InterventionError)
from app.interventions.handoff import ValidatedInterventionHandoff  # noqa: E402
from app.interventions.service import InterventionService  # noqa: E402
from app.results_cx.models import CriterionResult, Domain, Evaluation, SourceLineage  # noqa: E402


def synthetic_evaluations():
    evaluations = []
    for number in range(1, 5):
        criteria = [] if number == 4 else [CriterionResult(
            domain=Domain.MEMBER_EXPERIENCE, question="Synthetic closing summary clarity",
            answer="No", passed=False, max_score=Decimal(10), attained_score=Decimal(0),
            evaluator_feedback="Synthetic placeholder comment omitted from remote request",
            lineage=SourceLineage(source_filename="synthetic.xlsx", source_sheet="QA", excel_row=number + 1))]
        evaluations.append(Evaluation(internal_id=f"synthetic_{number}", agent_name="Synthetic Agent",
                                      qa_name="Synthetic Reviewer", team_leader="Synthetic Leader",
                                      call_date=date(2026, 1, number), criteria=criteria))
    return evaluations


async def main(skip_intervention: bool = False, skip_design: bool = False):
    settings = get_settings()
    if settings.diagnostic_evaluations_path is not None:
        raise SystemExit("Synthetic smoke refuses a configured local evaluations path")
    if not settings.bedrock_enabled:
        raise SystemExit("Set COACHLENS_BEDROCK_ENABLED=true for the synthetic smoke")
    evaluations = synthetic_evaluations()
    # The only way to unlock remote invocation: bind the reasoner to these in-memory synthetic
    # records. The same object attached to any other records refuses to send anything.
    service = DiagnosticService(
        evaluations,
        BedrockReasoner.for_synthetic_evaluations(settings.bedrock_region, settings.bedrock_model_id,
                                                  evaluations))
    signal = service.list_signals()[0]
    record = await service.diagnose(signal.signal_id)
    hypothesis = record.provider_hypothesis
    print({"status": record.status, "cause_domain": hypothesis.cause_domain.value,
           "confidence": str(hypothesis.provider_reported_confidence),
           "supporting_reference_count": len(hypothesis.supporting_evidence),
           "provider": hypothesis.provider_metadata.provider,
           "model": hypothesis.provider_metadata.model,
           "invocation_region": hypothesis.provider_metadata.invocation_region,
           "coverage": f"{signal.fail_count}/{signal.evaluated_results} results in "
                       f"{signal.evaluated_evaluations}/{signal.total_evaluations} evaluations"})
    # AWS-3: a separate Converse call reviews the same provider-safe population against the
    # proposal. It records a semantic outcome only; the record stays `awaiting_review`.
    response_diagnostics = []
    validations = EvidenceValidationService(
        service, BedrockEvidenceValidator(settings.bedrock_region, settings.bedrock_model_id,
                                         diagnostic_sink=response_diagnostics.append))
    try:
        validation = await validations.run(hypothesis.hypothesis_id)
    except ProviderOutputError:
        if response_diagnostics:
            print({"validator_response_diagnostic": response_diagnostics[-1]})
        raise
    print({"validation_outcome": validation.validation_outcome.value,
           "semantic_status": validation.semantic_status,
           "supported_reference_count": len(validation.supported_reference_ids),
           "contradicting_reference_count": len(validation.contradicting_reference_ids),
           "unsupported_claim_count": len(validation.unsupported_claims),
           "missing_evidence_count": len(validation.missing_evidence),
           "confidence": validation.provider_reported_confidence,
           "status_after_validation": service.get(hypothesis.hypothesis_id).status})
    if skip_intervention:
        return
    # AWS-4: a synthetic human approval, then two further separate Converse calls. The
    # intervention reasoner receives the approved diagnosis and the same provider-safe
    # population; the solution validator receives both plus the stored proposal.
    service.approve(hypothesis.hypothesis_id, "smoke")
    intervention_diagnostics = []
    interventions = InterventionService(
        service, validations,
        BedrockInterventionReasoner(settings.bedrock_region, settings.bedrock_model_id,
                                    diagnostic_sink=intervention_diagnostics.append),
        BedrockSolutionValidator(settings.bedrock_region, settings.bedrock_model_id,
                                 diagnostic_sink=intervention_diagnostics.append))
    try:
        proposed = await interventions.propose(hypothesis.hypothesis_id)
    except InterventionError:
        if intervention_diagnostics:
            print({"intervention_response_diagnostic": intervention_diagnostics[-1]})
        raise
    print({"intervention_type": proposed.proposal.intervention_type.value,
           "status": proposed.status,
           "evidence_review_status": proposed.evidence_review_status,
           "evidence_reference_count": len(proposed.proposal.evidence_reference_ids),
           "limitation_count": len(proposed.proposal.limitations),
           "missing_evidence_count": len(proposed.proposal.missing_evidence),
           "confidence": proposed.proposal.provider_reported_confidence,
           "training_design_gate": proposed.handoff.training_design_gate})
    try:
        validated = await interventions.validate_solution(hypothesis.hypothesis_id)
    except InterventionError:
        if intervention_diagnostics:
            print({"solution_response_diagnostic": intervention_diagnostics[-1]})
        raise
    review = validated.solution_validation
    print({"alignment_outcome": review.alignment_outcome.value,
           "solution_status": review.solution_status,
           "aligned_point_count": len(review.aligned_points),
           "misaligned_point_count": len(review.misaligned_points),
           "unsupported_assumption_count": len(review.unsupported_assumptions),
           "missing_information_count": len(review.missing_information),
           "confidence": review.provider_reported_confidence,
           "training_design_gate": validated.handoff.training_design_gate,
           "m5_decision_type": validated.handoff.decision_type.value,
           "diagnosis_status_after_aws4": service.get(hypothesis.hypothesis_id).status})
    if skip_design:
        return
    # AWS-5: the real design service reads the AWS-4 record through the handoff. The designer
    # is a separate Converse call that happens only for a permitted training or practice
    # intervention; withheld and questioned outcomes stop here with a fixed code.
    design_diagnostics = []
    designs = DesignService(service, ValidatedInterventionHandoff(interventions),
                            BedrockTrainingDesigner(settings.bedrock_region, settings.bedrock_model_id,
                                                    diagnostics=service, diagnostic_sink=design_diagnostics.append))
    try:
        result = await designs.run(hypothesis.hypothesis_id)
    except DesignError as exc:
        if design_diagnostics:
            print({"designer_response_diagnostic": design_diagnostics[-1]})
        print({"design_outcome": exc.code, "message": str(exc)})
        return
    summary = {"design_status": result.status, "generation_mode": result.generation_mode,
               "intervention_type": result.intervention.intervention_type,
               "training_design_gate": result.intervention.training_design_gate,
               "training_package": result.training_design is not None}
    if result.training_design is not None:
        design = result.training_design
        summary |= {"provider": design.provider_metadata.provider, "model": design.provider_metadata.model,
                    "validation_source": design.design_basis.intervention.validation_source,
                    "intervention_id_matches": design.design_basis.intervention.intervention_id == validated.proposal.intervention_id,
                    "training_focus": design.design_basis.intervention.training_focus.value,
                    "target_behaviors": len(design.target_behaviors), "objectives": len(design.objectives),
                    "knowledge_checks": len(design.decision_checks),
                    "practice_turns": sum(len(s.beats) for s in design.practice_scenarios),
                    "rubric_criteria": sum(len(s.rubric) for s in design.practice_scenarios),
                    "missing_operational_details": len(design.missing_operational_details),
                    "alignment_links": len(result.alignment_trace.links)}
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthetic Bedrock smoke for AWS-1, AWS-3, AWS-4, and AWS-5")
    parser.add_argument("--skip-intervention", action="store_true", help="Stop after the AWS-3 review")
    parser.add_argument("--skip-design", action="store_true", help="Stop after the AWS-4 solution review")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.skip_intervention, arguments.skip_design))
