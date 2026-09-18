"""Invoke AWS-1 with synthetic QA only. Uses the normal AWS credential provider chain."""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from app.config import get_settings  # noqa: E402
from app.diagnostics.bedrock import BedrockReasoner  # noqa: E402
from app.diagnostics.engine import DiagnosticService  # noqa: E402
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
    service = DiagnosticService(
        synthetic_evaluations(),
        BedrockReasoner(settings.bedrock_region, settings.bedrock_model_id, synthetic_evidence=True))
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


if __name__ == "__main__":
    asyncio.run(main())
