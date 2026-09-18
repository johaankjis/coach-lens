"""Invoke AWS-1 and AWS-3 with synthetic QA only. Uses the normal AWS credential provider chain."""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.diagnostics.bedrock import BedrockReasoner  # noqa: E402
from app.diagnostics.engine import DiagnosticService  # noqa: E402
from app.diagnostics.evidence_validator import BedrockEvidenceValidator, EvidenceValidationService  # noqa: E402
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


async def main():
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
    validations = EvidenceValidationService(
        service, BedrockEvidenceValidator(settings.bedrock_region, settings.bedrock_model_id))
    validation = await validations.run(hypothesis.hypothesis_id)
    print({"validation_outcome": validation.validation_outcome.value,
           "semantic_status": validation.semantic_status,
           "supported_reference_count": len(validation.supported_reference_ids),
           "contradicting_reference_count": len(validation.contradicting_reference_ids),
           "unsupported_claim_count": len(validation.unsupported_claims),
           "missing_evidence_count": len(validation.missing_evidence),
           "confidence": validation.provider_reported_confidence,
           "status_after_validation": service.get(hypothesis.hypothesis_id).status})


if __name__ == "__main__":
    asyncio.run(main())
