"""Synthetic-only M3 diagnostic contract tests."""

from datetime import date
from decimal import Decimal
import asyncio

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.diagnostics.engine import (ControlledTestReasoner, DiagnosticError,
                                    DiagnosticService, build_bundle, detect_signals,
                                    validate_provider_output)
from app.diagnostics.models import (CauseDomain, EvidenceReference, HumanRevision,
                                    PerformanceDimension)
from app.main import app
from app.results_cx.models import CriterionResult, Domain, Evaluation, SourceLineage


def evaluations():
    def criterion(question, passed, row, feedback=None):
        return CriterionResult(domain=Domain.COMPLIANCE, question=question,
                               answer="Yes" if passed else "No", passed=passed,
                               max_score=Decimal(10), attained_score=Decimal(10 if passed else 2),
                               evaluator_feedback=feedback,
                               lineage=SourceLineage(source_filename="synthetic.xlsx",
                                                     source_sheet="Sheet", excel_row=row))
    return [
        Evaluation(internal_id="eval_1", agent_name="Person One", qa_name="Reviewer One",
                   team_leader="Lead One", call_date=date(2026, 1, 1),
                   criteria=[criterion("Greeting", False, 2, "Person One missed greeting"),
                             criterion("Closure", True, 3)]),
        Evaluation(internal_id="eval_2", agent_name="Person Two", qa_name="Reviewer Two",
                   team_leader="Lead Two", call_date=date(2026, 1, 2),
                   criteria=[criterion("Greeting", False, 4), criterion("Closure", True, 5)]),
    ]


def response(associated_signal_id, **changes):
    raw = {"hypothesis_id": "hyp_1", "signal_id": associated_signal_id,
           "observed_behavioral_defect": "Greeting criterion failed in two evaluations",
           "cause_domain": "undetermined", "performance_dimension": "undetermined",
           "explanation": "Available facts establish failures but do not establish why.",
           "supporting_evidence": [{"item_id": "row_1", "evaluation_id": "eval_1"}],
           "conflicting_evidence": [], "missing_evidence": ["Ask reviewer for context"],
           "provider_reported_confidence": "0.2",
           "provider_metadata": {"provider": "controlled-test"}}
    return raw | changes


def prepared():
    source = evaluations()
    signal = detect_signals(source)[0]
    return source, signal, build_bundle(signal, source)


def test_signals_reuse_m2_aggregates_and_rank_deterministically():
    source, signal, bundle = prepared()
    reverse = detect_signals(list(reversed(source)))
    signals = detect_signals(source)
    assert [s.signal_id for s in signals] == [s.signal_id for s in reverse]
    assert [(s.criterion, s.fail_count) for s in signals] == [("Greeting", 2), ("Closure", 0)]
    assert (signal.evaluated_results, signal.evaluated_evaluations, signal.pass_count,
            signal.fail_count, signal.fail_rate, signal.feedback_coverage) == (2, 2, 0, 2, 1, Decimal("0.5"))
    assert signal.affected_evaluation_ids == ["eval_1", "eval_2"]
    assert signal.attained_score_total == 4
    assert signals[1].affected_evaluation_ids == []
    assert signals[1].pass_rate == 1
    assert bundle.items[0].source_lineage.excel_row == 2
    assert bundle.items[0].evaluator_feedback == "Person One missed greeting"


def test_provider_view_minimizes_identity_and_preserves_reference_lookup():
    source, signal, bundle = prepared()
    svc = DiagnosticService(source, ControlledTestReasoner(response(signal.signal_id)))
    view = svc.provider_evidence(signal.signal_id)
    serialized = view.model_dump_json()
    assert "Person One" not in serialized and "Reviewer One" not in serialized
    assert "synthetic.xlsx" not in serialized and "excel_row" not in serialized
    assert "[redacted] missed greeting" in serialized
    assert view.items[0].item_id == bundle.items[0].item_id
    assert "source_lineages" not in serialized
    assert "agent_name" not in serialized


@pytest.mark.parametrize("change,code", [
    ({"signal_id": "unknown"}, "evidence_mismatch"),
    ({"provider_reported_confidence": "1.01"}, "invalid_provider_output"),
    ({"cause_domain": "will_gap"}, "invalid_provider_output"),
    ({"explanation": ""}, "invalid_provider_output"),
    ({"missing_evidence": []}, "invalid_provider_output"),
    ({"supporting_evidence": []}, "invalid_provider_output"),
    ({"provider_reported_confidence": "NaN"}, "invalid_provider_output"),
    ({"supporting_evidence": [{"item_id": "row_99", "evaluation_id": "eval_1"}]}, "invalid_evidence_reference"),
    ({"supporting_evidence": [{"item_id": "row_1", "evaluation_id": "eval_2"}]}, "invalid_evidence_reference"),
    ({"supporting_evidence": [{"item_id": "signal", "evaluation_id": "eval_1"}]}, "invalid_evidence_reference"),
    ({"conflicting_evidence": [{"item_id": "row_1", "evaluation_id": "eval_1"}]}, "invalid_evidence_reference"),
])
def test_provider_output_is_untrusted(change, code):
    _, signal, bundle = prepared()
    with pytest.raises(DiagnosticError) as info:
        validate_provider_output(response(signal.signal_id, **change), bundle)
    assert info.value.code == code


def test_taxonomy_keeps_skill_will_distinct():
    assert CauseDomain.SKILL_GAP.value == "skill_gap"
    assert CauseDomain.KNOWLEDGE_GAP.value == "knowledge_gap"
    assert CauseDomain.PROCESS_GAP.value == "process_gap"
    assert PerformanceDimension.EXECUTION.value == "execution"
    assert PerformanceDimension.EXECUTION.value not in [x.value for x in CauseDomain]
    with pytest.raises(ValidationError):
        HumanRevision(observed_behavioral_defect="failure", cause_domain="will_gap",
                      performance_dimension="execution", explanation="explanation",
                      supporting_evidence=[], conflicting_evidence=[], missing_evidence=[])
    with pytest.raises(ValidationError):
        HumanRevision(observed_behavioral_defect="failure", cause_domain="undetermined",
                      performance_dimension="undetermined", explanation="unknown",
                      supporting_evidence=[], conflicting_evidence=[], missing_evidence=[])


def test_review_and_approval_gate():
    source, signal, _ = prepared()
    svc = DiagnosticService(source, ControlledTestReasoner(response(signal.signal_id)))
    record = asyncio.run(svc.diagnose(signal.signal_id))
    assert record.status == "awaiting_review"
    with pytest.raises(DiagnosticError, match="not been approved"):
        svc.get_approved_diagnosis("hyp_1")
    svc.approve("hyp_1", "human_1")
    approved = svc.get_approved_diagnosis("hyp_1")
    assert approved.human_revised is False and approved.approved_by == "human_1"
    assert approved.diagnosis.provider_metadata.provider == "controlled-test"
    with pytest.raises(DiagnosticError) as info:
        svc.reject("hyp_1", "human_1", "reason")
    assert info.value.code == "invalid_state_transition"
    assert record.events[0].occurred_at.tzinfo is not None


def test_reject_and_revision_audit():
    source, signal, _ = prepared()
    svc = DiagnosticService(source, ControlledTestReasoner(response(signal.signal_id)))
    asyncio.run(svc.diagnose(signal.signal_id))
    svc.reject("hyp_1", "human_2", "Insufficient context")
    with pytest.raises(DiagnosticError) as info:
        svc.get_approved_diagnosis("hyp_1")
    assert info.value.code == "diagnosis_not_approved"
    with pytest.raises(DiagnosticError):
        svc.approve("hyp_1", "human_2")

    svc = DiagnosticService(source, ControlledTestReasoner(response(signal.signal_id)))
    original = asyncio.run(svc.diagnose(signal.signal_id)).provider_hypothesis.model_dump()
    revision = HumanRevision(observed_behavioral_defect="Two failed greeting checks",
                             cause_domain="process_gap", performance_dimension="process_or_system",
                             explanation="Human reviewer found a process issue.",
                             supporting_evidence=[EvidenceReference(item_id="row_2", evaluation_id="eval_2")],
                             conflicting_evidence=[], missing_evidence=[])
    record = svc.revise("hyp_1", "human_3", revision, "Additional context reviewed")
    assert record.status == "revised" and not record.revision_approved
    assert record.provider_hypothesis.model_dump() == original
    with pytest.raises(DiagnosticError):
        svc.get_approved_diagnosis("hyp_1")
    with pytest.raises(DiagnosticError):
        svc.revise("hyp_1", "human_3", revision, "again")
    svc.approve("hyp_1", "human_4")
    approved = svc.get_approved_diagnosis("hyp_1")
    assert approved.human_revised and approved.diagnosis == revision
    assert [event.action for event in record.events] == ["revise", "approve"]
    assert record.events[0].revision == revision
    assert record.events[0].rationale == "Additional context reviewed"


def test_revision_references_are_validated():
    source, signal, _ = prepared()
    svc = DiagnosticService(source, ControlledTestReasoner(response(signal.signal_id)))
    asyncio.run(svc.diagnose(signal.signal_id))
    revision = HumanRevision(observed_behavioral_defect="failure", cause_domain="skill_gap",
                             performance_dimension="capability", explanation="Reviewed evidence",
                             supporting_evidence=[EvidenceReference(item_id="row_9", evaluation_id="eval_1")],
                             conflicting_evidence=[], missing_evidence=[])
    with pytest.raises(DiagnosticError) as info:
        svc.revise("hyp_1", "human", revision, "reviewed")
    assert info.value.code == "invalid_evidence_reference"
    assert svc.get("hyp_1").status == "awaiting_review"


def test_bundle_rejects_inconsistent_lineage():
    source, signal, _ = prepared()
    changed = signal.model_copy(deep=True)
    changed.source_lineages[0].excel_row = 999
    with pytest.raises(DiagnosticError) as info:
        build_bundle(changed, source)
    assert info.value.code == "evidence_mismatch"


def test_api_aggregate_safe_and_errors():
    source, signal, _ = prepared()
    prior = app.state.diagnostics
    app.state.diagnostics = DiagnosticService(source, ControlledTestReasoner(response(signal.signal_id)))
    try:
        with TestClient(app) as client:
            signals = client.get("/diagnostics/signals")
            assert signals.status_code == 200
            assert len(signals.json()) == 2
            assert "Person One" not in signals.text
            evidence = client.get(f"/diagnostics/signals/{signal.signal_id}/evidence")
            assert evidence.status_code == 200
            assert "Person One" not in evidence.text and "synthetic.xlsx" not in evidence.text
            assert client.get("/diagnostics/signals/missing/evidence").status_code == 404
            assert client.get("/diagnostics/hypotheses/missing").status_code == 404
            created = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
            assert created.status_code == 201
            assert client.get("/diagnostics/hypotheses/hyp_1/approved").status_code == 403
            assert client.post("/diagnostics/hypotheses/hyp_1/reject", json={"reviewer_id": "h", "rationale": ""}).status_code == 422
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "human"}).status_code == 200
            assert client.get("/diagnostics/hypotheses/hyp_1/approved").status_code == 200
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "human"}).status_code == 409
    finally:
        app.state.diagnostics = prior


def test_api_unavailable_reasoner_returns_structured_error():
    source, signal, _ = prepared()
    prior = app.state.diagnostics
    from app.main import UnavailableReasoner
    app.state.diagnostics = DiagnosticService(source, UnavailableReasoner())
    try:
        with TestClient(app) as client:
            response = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
            assert response.status_code == 503
            assert response.json()["detail"]["code"] == "reasoner_unavailable"
    finally:
        app.state.diagnostics = prior
