"""Run M4 with synthetic QA rows and a fixed, non-AI diagnostic fixture.

No ResultsCX data or reasoning provider is loaded. This script is a development-only
entry point; the normal API app retains its unavailable provider default.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.config import get_settings
from app.diagnostics.engine import DiagnosticService, detect_signals
from app.diagnostics.evidence_validator import EvidenceValidationService
from app.design.demo import DemoDesignFixture
from app.design.service import DesignService
from app.interventions.demo import DemoInterventionFixture, DemoSolutionFixture
from app.interventions.handoff import ValidatedInterventionHandoff
from app.interventions.service import InterventionService

# Settings also read a local `.env`, so check the resolved value rather than the environment
# alone. Refuse before `app.main` imports, because that import loads the configured records.
if get_settings().diagnostic_evaluations_path is not None:
    raise SystemExit("M4 synthetic demo refuses a real evaluations path")

from app.main import app  # noqa: E402
from app.results_cx.models import CriterionResult, Domain, Evaluation, SourceLineage
import uvicorn


def fixture_evaluations() -> list[Evaluation]:
    rows = []
    for number in range(1, 5):
        passed = number == 4
        rows.append(Evaluation(
            internal_id=f"demo_eval_{number:02d}", agent_name=f"Synthetic Agent {number}",
            qa_name="Synthetic QA Reviewer", team_leader="Synthetic Team Leader",
            call_date=date(2026, 1, number),
            criteria=[
                CriterionResult(domain=Domain.MEMBER_EXPERIENCE, question="Resolution summary clarity",
                                answer="Yes" if passed else "No", passed=passed,
                                max_score=Decimal("10"), attained_score=Decimal("10" if passed else "2"),
                                evaluator_feedback=("Synthetic feedback: summary was clear." if passed else
                                                    "Synthetic feedback: next steps were unclear."),
                                lineage=SourceLineage(source_filename="synthetic-demo.xlsx", source_sheet="QA",
                                                      excel_row=number + 1)),
                CriterionResult(domain=Domain.BUSINESS_PROCESS, question="Follow-up documented",
                                answer="Yes", passed=True, max_score=Decimal("5"),
                                attained_score=Decimal("5"), evaluator_feedback=None,
                                lineage=SourceLineage(source_filename="synthetic-demo-process.xlsx", source_sheet="QA",
                                                      excel_row=number + 1)),
            ]))
    return rows


class DemoFixtureReasoner:
    """Fixed fixture using bundle IDs only for valid citations; performs no inference."""

    controlled_fixture = True  # Reported by /diagnostics/mode from the object, not the label.

    def __init__(self, resolution_signal_id: str):
        self.resolution_signal_id = resolution_signal_id

    async def diagnose(self, evidence_bundle):
        items = evidence_bundle.items
        reference = lambda item: {"item_id": item.item_id, "evaluation_id": item.evaluation_id}  # noqa: E731
        if evidence_bundle.signal.signal_id != self.resolution_signal_id:
            return {
                "hypothesis_id": f"demo_hyp_{uuid4().hex}",
                "signal_id": evidence_bundle.signal.signal_id,
                "observed_behavioral_defect": "Synthetic QA records show no failed follow-up checks.",
                "cause_domain": "undetermined", "performance_dimension": "undetermined",
                "explanation": "Fixed demonstration text does not propose a cause for this all-pass signal.",
                "supporting_evidence": [{"item_id": "signal", "evaluation_id": None}],
                "conflicting_evidence": [],
                "missing_evidence": ["No failed criterion rows are present in this fixture."],
                "provider_reported_confidence": "0",
                "provider_metadata": {"provider": "m4-demo-fixture", "model": None},
            }
        failed = next(item for item in items if not item.passed)
        passed = next(item for item in items if item.passed)
        return {
            "hypothesis_id": f"demo_hyp_{uuid4().hex}",
            "signal_id": evidence_bundle.signal.signal_id,
            "observed_behavioral_defect": "Synthetic QA records show missed clarity checks.",
            "cause_domain": "skill_gap", "performance_dimension": "capability",
            "explanation": "Fixed demonstration text proposes a skill gap. It is deliberately not inferred from the QA rows.",
            "supporting_evidence": [reference(failed)],
            "conflicting_evidence": [reference(passed)],
            "missing_evidence": ["No direct observation of the agent's explanation process is in this fixture."],
            "provider_reported_confidence": "0.78",
            "provider_metadata": {"provider": "m4-demo-fixture", "model": None},
        }


class DemoFixtureEvidenceValidator:
    """Fixed synthetic review text for the M4 demo; performs no semantic inference."""

    controlled_fixture = True

    async def validate(self, request):
        resolution = request["signal"]["criterion"] == "Resolution summary clarity"
        return {
            "validation_outcome": "unsupported" if resolution else "supported",
            "support_assessment": (
                "The fixed skill-gap proposal exceeds these synthetic structured QA facts."
                if resolution else "The fixed undetermined proposal is appropriately restrained."),
            "supported_reference_ids": ["EVID-001"] if resolution else ["SIGNAL-001"],
            "contradicting_reference_ids": ["EVID-004"] if resolution else [],
            "unsupported_claims": ["A skill gap is not established by frequency alone."] if resolution else [],
            "missing_evidence": ["Direct observation of the explanation process"] if resolution else [],
            "provider_reported_confidence": 0.3 if resolution else 0.8,
        }


if __name__ == "__main__":
    evaluations = fixture_evaluations()
    resolution_signal_id = next(signal.signal_id for signal in detect_signals(evaluations)
                                if signal.criterion == "Resolution summary clarity")
    app.state.diagnostics = DiagnosticService(evaluations, DemoFixtureReasoner(resolution_signal_id))
    app.state.evidence_validations = EvidenceValidationService(app.state.diagnostics,
                                                               DemoFixtureEvidenceValidator())
    app.state.demo_mode = "synthetic_demo"
    # AWS-4: fixed intervention and solution-review fixtures. The M5 intervention step reads
    # their record through the handoff, so the training fixture only runs when the proposed
    # intervention is a training or practice type that the solution review did not question.
    app.state.interventions = InterventionService(app.state.diagnostics, app.state.evidence_validations,
                                                  DemoInterventionFixture(), DemoSolutionFixture())
    fixture = DemoDesignFixture(resolution_signal_id)
    app.state.designs = DesignService(app.state.diagnostics, ValidatedInterventionHandoff(app.state.interventions),
                                      fixture, controlled_fixture=True)
    uvicorn.run(app, host="127.0.0.1", port=8000)
