"""AWS-4 contracts use synthetic QA, controlled fixtures, and mocked Converse; no live AWS."""

import asyncio
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.design.demo import DemoDesignFixture
from app.design.models import InterventionDecision
from app.design.service import DesignError, DesignService, design_provider_kind
from app.design.validation import validate_decision
from app.diagnostics.bedrock import BedrockReasoner, SYSTEM_PROMPT as DIAGNOSTIC_PROMPT
from app.diagnostics.engine import ControlledTestReasoner, DiagnosticError, DiagnosticService
from app.diagnostics.evidence_validator import (SYSTEM_PROMPT as EVIDENCE_PROMPT,
                                                 ControlledTestEvidenceValidator, EvidenceValidationService)
from app.interventions.bedrock import (REASONER_FIELD_GUIDANCE, REASONER_PROMPT, REASONER_SHAPE_EXAMPLE,
                                       REASONER_SYSTEM_PROMPT, VALIDATOR_FIELD_GUIDANCE, VALIDATOR_PROMPT,
                                       VALIDATOR_SHAPE_EXAMPLE, VALIDATOR_SYSTEM_PROMPT,
                                       BedrockInterventionReasoner, BedrockSolutionValidator,
                                       InterventionError, InterventionOutputError, InterventionResponse,
                                       SolutionResponse, parse_intervention_response,
                                       parse_solution_response, reasoner_contract, validator_contract)
from app.interventions.demo import DemoInterventionFixture, DemoSolutionFixture
from app.interventions.handoff import ValidatedInterventionHandoff, decision_from_record
from app.interventions.models import InterventionRecord, build_handoff
from app.interventions.service import (ControlledInterventionReasoner, ControlledSolutionValidator,
                                       InterventionService, UnavailableInterventionReasoner,
                                       UnavailableSolutionValidator, build_intervention_context)
from app.main import app
from app.results_cx import demo
from test_bedrock import FakeRuntime, synthetic_reasoner
from test_diagnostics import evaluations, prepared, ref, response as diagnostic_response, revision
from test_results_cx_demo import generated_sources


def intervention_response(**changes):
    return {"intervention_type": "training",
            "recommendation": "Deliver a short knowledge module on the greeting requirements.",
            "rationale": "The validated diagnosis names a knowledge gap the agent cannot close unaided.",
            "target_change": "Open every call with the required greeting elements.",
            "fit_to_cause": "A knowledge gap in capability is addressed by instruction, not by coaching alone.",
            "evidence_reference_ids": ["EVID-001"], "limitations": ["Two evaluations only."],
            "missing_evidence": [], "provider_reported_confidence": 0.6} | changes


def solution_response(**changes):
    return {"alignment_outcome": "aligned",
            "alignment_assessment": "The intervention type fits the validated cause and targets the observed defect.",
            "aligned_points": ["Type fits the validated cause"], "misaligned_points": [],
            "unsupported_assumptions": [], "missing_information": [],
            "provider_reported_confidence": 0.7} | changes


def approved_diagnosis(diagnosis_changes=None, *, revised=False, revision_changes=None,
                       evidence_review=None, rows=None, revision_rationale="Observed process issue"):
    """A diagnosed, optionally semantically reviewed, optionally revised, approved diagnosis."""
    if rows is None:
        source, signal, bundle = prepared()
    else:
        source = rows
        from app.diagnostics.engine import build_bundle, detect_signals
        signal = detect_signals(source)[0]
        bundle = build_bundle(signal, source)
    diagnosis = DiagnosticService(source, ControlledTestReasoner(
        diagnostic_response(bundle, **(diagnosis_changes or {}))))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    reviews = None
    if evidence_review is not None:
        reviews = EvidenceValidationService(diagnosis, ControlledTestEvidenceValidator(evidence_review))
        asyncio.run(reviews.run("hyp_1"))
    if revised:
        diagnosis.revise("hyp_1", "lead", revision(bundle, **(revision_changes or {})), revision_rationale)
    diagnosis.approve("hyp_1", "lead")
    return diagnosis, reviews, bundle, signal


def build(diagnosis_changes=None, intervention_changes=None, solution_changes=None, **kwargs):
    diagnosis, reviews, bundle, signal = approved_diagnosis(diagnosis_changes, **kwargs)
    reasoner = ControlledInterventionReasoner(intervention_response(**(intervention_changes or {})))
    validator = ControlledSolutionValidator(solution_response(**(solution_changes or {})))
    service = InterventionService(diagnosis, reviews, reasoner, validator)
    return service, reasoner, validator, bundle, signal


def evidence_review(**changes):
    return {"validation_outcome": "supported", "support_assessment": "Observed defect is supported.",
            "supported_reference_ids": ["EVID-001"], "contradicting_reference_ids": [],
            "unsupported_claims": [], "missing_evidence": [], "provider_reported_confidence": 0.7} | changes


class ForbiddenTraining:
    controlled_fixture = True  # Keeps `design_provider_kind` consistent with the fixture flag.

    async def design(self, context, decision):
        raise AssertionError("Training must not run")


def design_service(service, signal, training=None):
    fixture = DemoDesignFixture(signal.signal_id)
    handoff = ValidatedInterventionHandoff(service)
    return DesignService(service.diagnostics, handoff, training or fixture, controlled_fixture=True)


def propose_and_validate(service):
    asyncio.run(service.propose("hyp_1"))
    return asyncio.run(service.validate_solution("hyp_1"))


# --- A: validated knowledge gap -> training can be proposed, validated, and designed -----------

def test_case_a_validated_knowledge_gap_can_lead_to_training():
    service, reasoner, validator, bundle, signal = build(
        {"cause_domain": "knowledge_gap", "performance_dimension": "capability",
         "explanation": "Agents were never told the greeting elements.", "missing_evidence": []})
    proposed = asyncio.run(service.propose("hyp_1"))
    assert proposed.status == "intervention_proposed" and proposed.solution_validation is None
    assert proposed.proposal.intervention_type == "training"
    assert proposed.handoff.training_design_gate == "awaiting_solution_validation"
    assert proposed.handoff.decision_type == "training" and proposed.handoff.human_reviewed_intervention is False
    assert reasoner.requests[0]["validated_diagnosis"]["cause_domain"] == "knowledge_gap"
    record = asyncio.run(service.validate_solution("hyp_1"))
    assert record.status == "solution_validated" and record.solution_validation.alignment_outcome == "aligned"
    assert record.handoff.training_design_gate == "permitted"
    assert validator.requests[0]["proposed_intervention"]["intervention_type"] == "training"
    assert validator.requests[0]["validated_diagnosis"] == reasoner.requests[0]["validated_diagnosis"]
    result = asyncio.run(design_service(service, signal).run("hyp_1"))
    assert result.status == "ready_for_alignment_review" and result.training_design is not None
    assert result.intervention.decision_type == "training" and result.intervention.intervention_type == "training"
    assert result.intervention.solution_alignment == "aligned"
    assert result.intervention.intervention_id == record.proposal.intervention_id
    assert result.intervention.solution_validation_id == record.solution_validation.solution_validation_id
    assert result.intervention.target_change == record.proposal.target_change
    assert result.intervention.next_actions[0].instructions == record.proposal.recommendation
    assert result.intervention.provider_metadata.generation_mode is None
    assert result.generation_mode == "controlled_fixture"


# --- B: validated skill gap -> practice, simulation, or coaching -------------------------------

def test_case_b_validated_skill_gap_practice_can_be_designed():
    service, _, _, _, signal = build(
        {"cause_domain": "skill_gap", "performance_dimension": "capability",
         "explanation": "Agents know the elements but stumble delivering them.", "missing_evidence": []},
        {"intervention_type": "practice_simulation",
         "recommendation": "Rehearse the greeting in simulated calls with feedback."})
    record = propose_and_validate(service)
    assert record.proposal.intervention_type == "practice_simulation"
    assert record.handoff.decision_type == "training" and record.handoff.training_design_gate == "permitted"
    result = asyncio.run(design_service(service, signal).run("hyp_1"))
    assert result.training_design is not None and result.intervention.intervention_type == "practice_simulation"


def test_case_b_validated_skill_gap_coaching_never_enters_the_training_generator():
    service, _, _, _, signal = build(
        {"cause_domain": "skill_gap", "performance_dimension": "execution",
         "explanation": "The agent has greeted correctly on other calls.", "missing_evidence": []},
        {"intervention_type": "coaching", "recommendation": "Supervisor side-by-side coaching on two calls."},
        {"aligned_points": ["Coaching fits an execution issue where capability exists"]})
    record = propose_and_validate(service)
    assert record.handoff.decision_type == "non_training"
    assert record.handoff.training_design_gate == "not_applicable"
    result = asyncio.run(design_service(service, signal, ForbiddenTraining()).run("hyp_1"))
    assert result.status == "alternative_recommended" and result.training_design is None
    assert result.intervention.intervention_type == "coaching"


# --- C: validated process gap -> training-only intervention is questioned ---------------------

def test_case_c_process_gap_met_with_training_is_misaligned_and_training_is_withheld():
    service, reasoner, validator, _, signal = build(
        None, {"intervention_type": "training", "evidence_reference_ids": ["EVID-002"],
               "rationale": "Every greeting failed, so train the agents on the greeting."},
        {"alignment_outcome": "misaligned", "aligned_points": [],
         "misaligned_points": ["Training an agent does not correct a validated process gap"],
         "unsupported_assumptions": ["Failure count implies a training need"],
         "alignment_assessment": "The reviewer validated a process gap; agent training does not address it."},
        revised=True)
    record = propose_and_validate(service)
    assert reasoner.requests[0]["validated_diagnosis"]["cause_domain"] == "process_gap"
    assert record.status == "solution_questioned"
    assert record.solution_validation.alignment_outcome == "misaligned"
    assert record.handoff.training_design_gate == "withheld" and record.handoff.decision_type == "training"
    designs = design_service(service, signal, ForbiddenTraining())
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.run("hyp_1"))
    assert error.value.code == "training_design_withheld"
    with pytest.raises(DesignError, match="No design run"):
        designs.get("hyp_1")
    # The questioned review changed nothing upstream.
    assert service.diagnostics.get_approved_diagnosis("hyp_1").diagnosis.cause_domain == "process_gap"


def test_case_c_process_correction_for_a_process_gap_is_a_non_training_result():
    service, _, _, _, signal = build(
        None, {"intervention_type": "process_correction", "evidence_reference_ids": ["EVID-002"],
               "recommendation": "Correct the greeting script step in the call flow."},
        {"aligned_points": ["A process change addresses the validated process gap"]}, revised=True)
    record = propose_and_validate(service)
    assert record.handoff.training_design_gate == "not_applicable"
    result = asyncio.run(design_service(service, signal, ForbiddenTraining()).run("hyp_1"))
    assert result.status == "alternative_recommended" and result.intervention.intervention_type == "process_correction"


# --- D: undetermined diagnosis -> investigate rather than invented training --------------------

def test_case_d_undetermined_diagnosis_leads_to_investigation_not_training():
    service, _, _, _, signal = build(
        None, {"intervention_type": "investigate_further",
               "recommendation": "Collect evaluator observations before selecting an intervention.",
               "missing_evidence": ["Evaluator comments describing what the agent said"]},
        {"aligned_points": ["Investigation matches an undetermined cause"]})
    record = propose_and_validate(service)
    assert record.validated_diagnosis.diagnosis.cause_domain == "undetermined"
    assert record.handoff.decision_type == "investigate" and record.handoff.training_design_gate == "not_applicable"
    result = asyncio.run(design_service(service, signal, ForbiddenTraining()).run("hyp_1"))
    assert result.status == "evidence_required" and result.training_design is None
    assert "Evaluator comments describing what the agent said" in result.intervention.unresolved_questions


def test_case_d_investigation_without_missing_evidence_fails_closed():
    service, _, _, _, _ = build(None, {"intervention_type": "investigate_further", "missing_evidence": []})
    with pytest.raises(InterventionOutputError) as error:
        asyncio.run(service.propose("hyp_1"))
    assert error.value.code == "invalid_intervention_output"
    with pytest.raises(InterventionError, match="No intervention"):
        service.get("hyp_1")


# --- E: high failure frequency alone does not justify training --------------------------------

def test_case_e_frequency_alone_training_claim_is_questioned_with_the_facts_in_view():
    service, reasoner, validator, _, _ = build(
        {"cause_domain": "knowledge_gap", "performance_dimension": "capability",
         "explanation": "A 100% failure rate proves the agents lack knowledge.", "missing_evidence": []},
        {"rationale": "Every evaluated greeting failed, so training is required."},
        {"alignment_outcome": "partially_aligned",
         "aligned_points": ["Training can address a validated knowledge gap"],
         "unsupported_assumptions": ["A 100% failure rate by itself establishes a training need"],
         "missing_information": ["What the agents were actually taught"]})
    record = propose_and_validate(service)
    assert reasoner.requests[0]["signal"]["failure_rate"] == "1"
    assert validator.requests[0]["signal"]["failed_criterion_result_count"] == 2
    assert record.status == "solution_questioned" and record.solution_validation.unsupported_assumptions
    assert record.handoff.training_design_gate == "permitted"  # Questioned, not withheld, for partial alignment.
    for prompt, fragment in ((REASONER_PROMPT, "frequency alone never justifies training"),
                             (REASONER_PROMPT, "A performance problem does not automatically mean training"),
                             (VALIDATOR_PROMPT, "Never equate a high failure rate with a training need"),
                             (VALIDATOR_PROMPT, "approval of the diagnosis with approval of training"),
                             (VALIDATOR_PROMPT, "recurrence with a\nknowledge gap")):
        assert fragment in prompt, fragment


def test_case_e_model_cannot_add_statistics_to_either_output():
    for changes in ({"failure_rate": "1.0"}, {"training_need_score": 0.9}):
        service, _, _, _, _ = build(None, changes)
        with pytest.raises(InterventionOutputError):
            asyncio.run(service.propose("hyp_1"))
    service, _, _, _, _ = build(None, None, {"failure_rate": "1.0"})
    asyncio.run(service.propose("hyp_1"))
    with pytest.raises(InterventionOutputError) as error:
        asyncio.run(service.validate_solution("hyp_1"))
    assert error.value.code == "invalid_solution_output"


# --- F: the solution validator cannot alter the diagnosis -------------------------------------

@pytest.mark.parametrize("change", [
    {"cause_domain": "process_gap"}, {"revised_diagnosis": {"cause_domain": "skill_gap"}},
    {"performance_dimension": "execution"}, {"replacement_intervention": "coaching"},
    {"alignment_outcome": "approved"}, {"human_approved": True},
])
def test_case_f_solution_validator_output_that_touches_the_diagnosis_fails_closed(change):
    service, _, _, _, _ = build(None, None, change)
    before = service.diagnostics.get("hyp_1")
    proposed = asyncio.run(service.propose("hyp_1"))
    with pytest.raises(InterventionOutputError) as error:
        asyncio.run(service.validate_solution("hyp_1"))
    assert error.value.code == "invalid_solution_output"
    assert service.diagnostics.get("hyp_1") == before
    assert service.get("hyp_1") == proposed  # The proposal survives; no validation was stored.


def test_case_f_solution_validation_leaves_diagnosis_and_records_immutable():
    service, _, _, _, _ = build(None, None, {"alignment_outcome": "misaligned", "aligned_points": [],
                                             "misaligned_points": ["Type does not fit"]})
    before = service.diagnostics.get("hyp_1")
    approved_before = service.diagnostics.get_approved_diagnosis("hyp_1")
    record = propose_and_validate(service)
    assert service.diagnostics.get("hyp_1") == before
    assert service.diagnostics.get_approved_diagnosis("hyp_1") == approved_before
    assert record.validated_diagnosis == approved_before
    assert record.solution_validation.assessed == "proposed_intervention"
    with pytest.raises(ValidationError):
        record.validated_diagnosis.diagnosis.cause_domain = "skill_gap"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        record.solution_validation.alignment_outcome = "aligned"  # type: ignore[misc]
    record.proposal.limitations  # tuple, not a shared list
    copy = service.get("hyp_1")
    assert copy == record and copy is not record


# --- G: the provider cannot fabricate evidence references -------------------------------------

@pytest.mark.parametrize("refs", [
    ["EVID-999"], ["EVID-002"], ["SIGNAL-001"], ["EVID-001", "EVID-001"], ["ev_invented"],
    [], ["EVID-1"], [{"item_id": "signal"}],
])
def test_case_g_reasoner_may_cite_only_what_the_validated_diagnosis_cited(refs):
    service, reasoner, _, bundle, _ = build(None, {"evidence_reference_ids": refs})
    with pytest.raises(InterventionOutputError) as error:
        asyncio.run(service.propose("hyp_1"))
    assert error.value.code == "invalid_intervention_output"
    assert len(reasoner.requests) == 1
    assert reasoner.requests[0]["citation_roles"] == {"supporting_reference_ids": ["EVID-001"],
                                                      "conflicting_reference_ids": []}
    with pytest.raises(InterventionError) as absent:
        service.get("hyp_1")
    assert absent.value.code == "intervention_not_found"


def test_case_g_valid_citations_resolve_locally_and_pass_the_m5_gate():
    service, _, _, bundle, signal = build(None, {"evidence_reference_ids": ["EVID-001"]})
    record = propose_and_validate(service)
    assert record.proposal.evidence_reference_ids == ("EVID-001",)
    assert record.proposal.evidence_refs[0].item_id == bundle.items[0].item_id
    assert record.proposal.evidence_refs[0].evaluation_id == bundle.items[0].evaluation_id
    designs = design_service(service, signal)
    context = designs._context("hyp_1")
    decision = validate_decision(decision_from_record(record, context), context)
    assert decision.evidence_refs[0] in context.allowed_evidence
    # A record whose refs fall outside the approved citations cannot pass M5 either.
    forged = decision_from_record(record, context) | {"evidence_refs": [ref(bundle, 1)]}
    from app.design.validation import InvalidDesignOutput
    with pytest.raises(InvalidDesignOutput, match="outside approved diagnosis"):
        validate_decision(forged, context)


# --- H: malformed or extra-key output fails closed --------------------------------------------

@pytest.mark.parametrize("change", [
    {"intervention_type": "workshop"}, {"intervention_type": None}, {"recommendation": ""},
    {"recommendation": " "}, {"provider_reported_confidence": "0.5"},
    {"provider_reported_confidence": "moderate"}, {"provider_reported_confidence": 1.5},
    {"provider_reported_confidence": True}, {"provider_reported_confidence": None},
    {"limitations": "one limitation"}, {"limitations": [" "]}, {"missing_evidence": None},
    {"generation_mode": "provider"}, {"provider": "Amazon Bedrock"}, {"model": "forged"},
    {"hypothesis_id": "hyp_1"}, {"intervention_id": "int_forged"}, {"decision_type": "training"},
    {"status": "solution_validated"}, {"rationale": "x" * 4001},
])
def test_case_h_malformed_intervention_output_fails_closed_and_can_be_retried(change):
    service, reasoner, _, _, _ = build(None, change)
    with pytest.raises(InterventionOutputError) as error:
        asyncio.run(service.propose("hyp_1"))
    assert error.value.code == "invalid_intervention_output"
    with pytest.raises(InterventionError):
        service.get("hyp_1")
    reasoner.response = intervention_response()
    assert asyncio.run(service.propose("hyp_1")).status == "intervention_proposed"
    assert len(reasoner.requests) == 2


def test_case_h_missing_keys_and_non_mapping_output_fail_closed():
    for key in InterventionResponse.model_fields:
        service, _, _, _, _ = build(None, None)
        service.reasoner.response = {k: v for k, v in intervention_response().items() if k != key}
        with pytest.raises(InterventionOutputError):
            asyncio.run(service.propose("hyp_1"))
    for raw in (None, [], 42, "training", object()):
        service, _, _, _, _ = build()
        service.reasoner.response = raw
        with pytest.raises(InterventionOutputError):
            asyncio.run(service.propose("hyp_1"))


@pytest.mark.parametrize("change", [
    {"alignment_outcome": "aligned", "aligned_points": []},
    {"alignment_outcome": "aligned", "misaligned_points": ["A mismatch"]},
    {"alignment_outcome": "partially_aligned", "aligned_points": []},
    {"alignment_outcome": "misaligned", "aligned_points": [], "misaligned_points": [], "unsupported_assumptions": []},
    {"alignment_outcome": "insufficient_evidence", "missing_information": []},
    {"alignment_outcome": "certain"}, {"provider_reported_confidence": "high"},
    {"provider_reported_confidence": "0.7"}, {"aligned_points": "fits"}, {"aligned_points": [""]},
    {"alignment_assessment": ""}, {"generation_mode": "provider"}, {"solution_validation_id": "sol_forged"},
])
def test_case_h_incoherent_or_malformed_solution_output_fails_closed(change):
    service, _, validator, _, _ = build(None, None, change)
    proposed = asyncio.run(service.propose("hyp_1"))
    with pytest.raises(InterventionOutputError) as error:
        asyncio.run(service.validate_solution("hyp_1"))
    assert error.value.code == "invalid_solution_output" and len(validator.requests) == 1
    assert service.get("hyp_1") == proposed and service.get("hyp_1").solution_validation is None
    validator.response = solution_response()
    assert asyncio.run(service.validate_solution("hyp_1")).status == "solution_validated"


@pytest.mark.parametrize("text", ["not json", "```json\n{}\n```", "[]",
                                  json.dumps(intervention_response()) + " extra"])
def test_case_h_parsers_reject_non_object_documents(text):
    with pytest.raises(InterventionOutputError):
        parse_intervention_response(text, {"EVID-001"})
    with pytest.raises(InterventionOutputError):
        parse_solution_response(text)


def test_case_h_bedrock_non_end_turn_fences_and_errors_fail_closed_without_fallback():
    rows = evaluations()
    diagnosis = DiagnosticService(rows, synthetic_reasoner(rows))
    hypothesis_id = asyncio.run(diagnosis.diagnose(diagnosis.list_signals()[0].signal_id)).provider_hypothesis.hypothesis_id
    diagnosis.approve(hypothesis_id, "lead")
    for runtime in (FakeRuntime(error=RuntimeError("secret")),
                    FakeRuntime(text=json.dumps(intervention_response()), stop_reason="max_tokens"),
                    FakeRuntime(text="```json\n" + json.dumps(intervention_response()) + "\n```")):
        service = InterventionService(diagnosis, None, BedrockInterventionReasoner(client=runtime),
                                      BedrockSolutionValidator(client=runtime))
        with pytest.raises(InterventionError) as error:
            asyncio.run(service.propose(hypothesis_id))
        assert error.value.code in ("intervention_provider_failure", "invalid_intervention_output")
        assert "secret" not in str(error.value)
        with pytest.raises(InterventionError):
            service.get(hypothesis_id)
        assert len(runtime.calls) == 1


# --- I: repeated invocation is idempotent -----------------------------------------------------

def test_case_i_repeat_and_concurrent_requests_do_not_call_the_provider_again():
    service, reasoner, validator, _, _ = build()

    async def twice(call):
        return await asyncio.gather(call("hyp_1"), call("hyp_1"))

    first, second = asyncio.run(twice(service.propose))
    assert first == second and len(reasoner.requests) == 1
    assert asyncio.run(service.propose("hyp_1")) == first
    validated_a, validated_b = asyncio.run(twice(service.validate_solution))
    assert validated_a == validated_b and len(validator.requests) == 1
    assert validated_a.proposal == first.proposal and validated_a.created_at == first.created_at
    assert validated_a.updated_at >= first.updated_at
    # After validation, a repeat proposal returns the validated record rather than re-proposing.
    assert asyncio.run(service.propose("hyp_1")) == validated_a
    assert asyncio.run(service.validate_solution("hyp_1")) == validated_a
    assert len(reasoner.requests) == 1 and len(validator.requests) == 1


def test_case_i_solution_validation_requires_a_stored_proposal():
    service, _, validator, _, _ = build()
    with pytest.raises(InterventionError) as error:
        asyncio.run(service.validate_solution("hyp_1"))
    assert error.value.code == "intervention_not_found" and not validator.requests


# --- J: the human revision is what AWS-4 reasons from -----------------------------------------

def test_case_j_reasoner_and_validator_receive_the_human_revision_not_the_stale_proposal():
    service, reasoner, validator, bundle, _ = build(
        None, {"intervention_type": "process_correction", "evidence_reference_ids": ["EVID-002"]},
        None, revised=True, evidence_review=evidence_review(validation_outcome="unsupported",
                                                            unsupported_claims=["Cause not shown"]))
    record = propose_and_validate(service)
    for request in (reasoner.requests[0], validator.requests[0]):
        validated = request["validated_diagnosis"]
        assert validated["cause_domain"] == "process_gap" and validated["performance_dimension"] == "undetermined"
        assert validated["explanation"] == "Human reviewer found a process issue."
        assert validated["observed_behavioral_defect"] == "Two failed greeting checks"
        assert request["citation_roles"] == {"supporting_reference_ids": ["EVID-002"],
                                             "conflicting_reference_ids": []}
        assert request["human_validation"] == {"human_revised": True,
                                               "revision_rationale": "Observed process issue"}
        serialized = json.dumps(request)
        assert "Available facts establish failures" not in serialized  # Superseded provider explanation.
        assert "undetermined" not in json.dumps(validated["cause_domain"])
        assert "lead" not in serialized.split('"revision_rationale"')[0]  # Reviewer identifier is never sent.
    assert record.validated_diagnosis.human_revised is True
    assert record.validated_diagnosis.diagnosis.cause_domain == "process_gap"
    assert record.validated_diagnosis.approved_by == "lead"  # Kept locally for audit only.
    assert record.proposal.evidence_refs[0].item_id == bundle.items[1].item_id
    # The AWS-3 review described the original proposal; provenance says so rather than
    # presenting it as a review of the revision.
    assert record.evidence_review_status == "original_proposal_only"
    assert record.semantic_review.validation_outcome == "unsupported"
    assert record.semantic_review.describes_validated_diagnosis is False


def test_case_j_approved_original_carries_its_semantic_status_verbatim():
    for outcome, status in (("supported", "evidence_validated"), ("partially_supported", "evidence_questioned")):
        service, _, _, _, _ = build(evidence_review=evidence_review(validation_outcome=outcome))
        record = asyncio.run(service.propose("hyp_1"))
        assert record.evidence_review_status == status
        assert record.semantic_review.semantic_status == status
        assert record.semantic_review.describes_validated_diagnosis is True
        assert record.semantic_review.assessed_proposal == "provider_hypothesis"
    service, _, _, _, _ = build()
    assert asyncio.run(service.propose("hyp_1")).evidence_review_status == "not_reviewed"
    assert asyncio.run(service.propose("hyp_1")).semantic_review is None


def test_semantic_review_is_not_a_gate_on_human_action_or_on_aws4():
    """An unsupported AWS-3 outcome neither blocks approval nor blocks the intervention stages."""
    service, reasoner, _, _, _ = build(evidence_review=evidence_review(
        validation_outcome="unsupported", unsupported_claims=["Cause not shown"]))
    record = propose_and_validate(service)
    assert record.evidence_review_status == "evidence_questioned" and record.status == "solution_validated"
    # The semantic review is provenance, not provider input.
    assert "semantic" not in json.dumps(reasoner.requests[0]) and "evidence_validated" not in json.dumps(reasoner.requests[0])


# --- Privacy ------------------------------------------------------------------------------------

def test_wire_carries_no_reviewer_identity_local_ids_comments_or_lineage():
    service, reasoner, validator, bundle, _ = build(None, {"evidence_reference_ids": ["EVID-002"]}, revised=True)
    propose_and_validate(service)
    for request in (reasoner.requests[0], validator.requests[0]):
        wire = json.dumps(request)
        for forbidden in ("lead", "Person One", "Reviewer One", "Lead One", "eval_1", "eval_2", "ev_", "sig_",
                          "synthetic.xlsx", "Sheet", "source_lineage", "evaluator_feedback", "answer",
                          "evaluation_id", "item_id", "agent_name", "qa_name", "team_leader", "approved_by",
                          "reviewer_id", "hypothesis_id", "missed greeting"):
            assert forbidden not in wire, forbidden
        assert bundle.items[0].item_id not in wire
    assert set(reasoner.requests[0]) == {"signal", "evidence_items", "text_coverage", "validated_diagnosis",
                                         "citation_roles", "human_validation"}
    assert set(validator.requests[0]) == set(reasoner.requests[0]) | {"proposed_intervention"}
    assert set(validator.requests[0]["proposed_intervention"]) == set(InterventionResponse.model_fields)


@pytest.mark.parametrize("kwargs", [
    {"diagnosis_changes": {"explanation": "Person One missed greeting on eval_1"}},
    {"revised": True, "revision_rationale": "Person One told me the script changed"},
    {"revised": True, "revision_changes": {"explanation": "See row 2 of synthetic.xlsx"}},
])
def test_local_identifiers_in_validated_text_block_the_wire(kwargs):
    service, reasoner, validator, _, _ = build(**kwargs)
    with pytest.raises(DiagnosticError) as error:
        asyncio.run(service.propose("hyp_1"))
    assert error.value.code == "provider_privacy_blocked" and not reasoner.requests and not validator.requests


def test_remote_adapters_require_a_bound_bedrock_diagnosis():
    # A fixture diagnosis population never reaches Bedrock through AWS-4.
    diagnosis, _, _, _ = approved_diagnosis()
    runtime = FakeRuntime(text=json.dumps(intervention_response()))
    service = InterventionService(diagnosis, None, BedrockInterventionReasoner(client=runtime),
                                  BedrockSolutionValidator(client=runtime))
    with pytest.raises(InterventionError) as error:
        asyncio.run(service.propose("hyp_1"))
    assert error.value.code == "provider_privacy_blocked" and runtime.calls == []
    # A privacy-blocked (unbound) Bedrock diagnostic reasoner also blocks AWS-4.
    diagnosis.reasoner = BedrockReasoner(client=FakeRuntime())
    with pytest.raises(InterventionError) as error:
        asyncio.run(service.propose("hyp_1"))
    assert error.value.code == "provider_privacy_blocked" and runtime.calls == []
    # The validator is gated independently, even after a fixture proposal.
    fixture_service = InterventionService(diagnosis, None, ControlledInterventionReasoner(intervention_response()),
                                          BedrockSolutionValidator(client=runtime))
    asyncio.run(fixture_service.propose("hyp_1"))
    with pytest.raises(InterventionError) as error:
        asyncio.run(fixture_service.validate_solution("hyp_1"))
    assert error.value.code == "provider_privacy_blocked" and runtime.calls == []


def test_case_k_real_structured_only_boundary_holds_for_both_aws4_calls(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    reasoning_runtime = FakeRuntime()
    diagnosis = DiagnosticService(trusted, BedrockReasoner.for_trusted_results_cx(
        "us-east-1", "global.anthropic.claude-sonnet-4-6", trusted, client=reasoning_runtime))
    signal = diagnosis.list_signals()[0]
    hypothesis_id = asyncio.run(diagnosis.diagnose(signal.signal_id)).provider_hypothesis.hypothesis_id
    diagnosis.approve(hypothesis_id, "supervisor-real")
    reasoner_runtime = FakeRuntime(text=json.dumps(intervention_response()))
    validator_runtime = FakeRuntime(text=json.dumps(solution_response()))
    service = InterventionService(diagnosis, None, BedrockInterventionReasoner(client=reasoner_runtime),
                                  BedrockSolutionValidator(client=validator_runtime))
    asyncio.run(service.propose(hypothesis_id))
    record = asyncio.run(service.validate_solution(hypothesis_id))
    assert record.status == "solution_validated"
    assert record.proposal.provider_metadata.generation_mode == "provider"
    original = json.loads(reasoning_runtime.calls[0]["messages"][0]["content"][0]["text"])
    for runtime in (reasoner_runtime, validator_runtime):
        request = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
        assert request["signal"] == original["signal"]
        assert request["evidence_items"] == original["evidence_items"]
        assert request["text_coverage"] == original["text_coverage"]
        assert request["text_coverage"]["text_items_blocked"] == 2
        assert request["text_coverage"]["minimized_text_items_allowed"] == 0
        serialized = json.dumps(runtime.calls)
        for evaluation in trusted:
            for criterion in evaluation.criteria:
                if criterion.evaluator_feedback:
                    assert criterion.evaluator_feedback not in serialized
            for name in (evaluation.agent_name, evaluation.qa_name, evaluation.team_leader, evaluation.internal_id):
                assert name not in serialized
        for forbidden in ("diagnostic_text", "minimized_evaluator_feedback", "eval_", "ev_", "sig_",
                          "source_lineage", "source_filename", "source_sheet", "excel_row", "agent_name",
                          "qa_name", "team_leader", "internal_id", "supervisor-real", ".xlsx"):
            assert forbidden not in serialized, forbidden
    assert reasoner_runtime.calls[0]["system"][0]["text"] != validator_runtime.calls[0]["system"][0]["text"]
    assert record.validated_diagnosis.approved_by == "supervisor-real"


# --- Provenance ---------------------------------------------------------------------------------

def test_bedrock_provenance_is_stamped_locally_with_separate_prompts():
    rows = evaluations()
    reasoning_runtime = FakeRuntime()
    diagnosis = DiagnosticService(rows, synthetic_reasoner(rows, reasoning_runtime))
    hypothesis_id = asyncio.run(diagnosis.diagnose(diagnosis.list_signals()[0].signal_id)).provider_hypothesis.hypothesis_id
    diagnosis.approve(hypothesis_id, "lead")
    reasoner_runtime = FakeRuntime(text=json.dumps(intervention_response()))
    validator_runtime = FakeRuntime(text=json.dumps(solution_response()))
    service = InterventionService(diagnosis, None, BedrockInterventionReasoner(client=reasoner_runtime),
                                  BedrockSolutionValidator(client=validator_runtime))
    asyncio.run(service.propose(hypothesis_id))
    record = asyncio.run(service.validate_solution(hypothesis_id))
    for metadata in (record.proposal.provider_metadata, record.solution_validation.provider_metadata):
        assert metadata.provider == "Amazon Bedrock"
        assert metadata.model == "global.anthropic.claude-sonnet-4-6"
        assert metadata.invocation_region == "us-east-1"
        assert metadata.generation_mode == "provider"
        assert metadata.generated_at is not None
    prompts = {reasoning_runtime.calls[0]["system"][0]["text"], reasoner_runtime.calls[0]["system"][0]["text"],
               validator_runtime.calls[0]["system"][0]["text"], EVIDENCE_PROMPT, DIAGNOSTIC_PROMPT}
    assert len(prompts) == 4  # AWS-1, AWS-3, AWS-4 reasoner, AWS-4 validator all differ.
    assert reasoner_runtime.calls[0]["system"][0]["text"] == REASONER_SYSTEM_PROMPT
    assert validator_runtime.calls[0]["system"][0]["text"] == VALIDATOR_SYSTEM_PROMPT
    assert reasoner_runtime.calls[0]["inferenceConfig"] == {"maxTokens": 1600, "temperature": 0}
    assert record.proposal.intervention_id.startswith("int_")
    assert record.solution_validation.solution_validation_id.startswith("sol_")
    assert record.solution_validation.intervention_id == record.proposal.intervention_id
    assert record.handoff.intervention_id == record.proposal.intervention_id
    assert diagnosis.get(hypothesis_id).status == "approved"


def test_fixture_provenance_and_provider_kinds_come_from_the_objects():
    service, reasoner, validator, _, signal = build()
    record = propose_and_validate(service)
    assert record.proposal.provider_metadata.generation_mode == "controlled_fixture"
    assert record.solution_validation.provider_metadata.generation_mode == "controlled_fixture"
    assert record.proposal.provider_metadata.provider == "controlled fixture"
    handoff = ValidatedInterventionHandoff(service)
    assert design_provider_kind(handoff, DemoDesignFixture(signal.signal_id)) == "controlled_fixture"
    assert design_provider_kind(ValidatedInterventionHandoff(InterventionService(
        service.diagnostics, None, UnavailableInterventionReasoner(), UnavailableSolutionValidator())),
        DemoDesignFixture(signal.signal_id)) == "controlled_fixture"
    assert design_provider_kind(ValidatedInterventionHandoff(InterventionService(
        service.diagnostics, None, BedrockInterventionReasoner(client=FakeRuntime()), validator)),
        DemoDesignFixture(signal.signal_id)) == "provider"
    with pytest.raises(DesignError, match="controlled_fixture flag"):
        DesignService(service.diagnostics, handoff, DemoDesignFixture(signal.signal_id), controlled_fixture=False)


# --- Contracts ----------------------------------------------------------------------------------

def test_prompts_render_from_the_schemas_and_examples_parse():
    assert REASONER_SYSTEM_PROMPT == REASONER_PROMPT + "\n\n" + reasoner_contract()
    assert VALIDATOR_SYSTEM_PROMPT == VALIDATOR_PROMPT + "\n\n" + validator_contract()
    assert set(REASONER_SHAPE_EXAMPLE) == set(InterventionResponse.model_fields) == set(REASONER_FIELD_GUIDANCE)
    assert set(VALIDATOR_SHAPE_EXAMPLE) == set(SolutionResponse.model_fields) == set(VALIDATOR_FIELD_GUIDANCE)
    assert "exactly these nine keys, all required, and no other keys" in reasoner_contract()
    assert "exactly these seven keys, all required, and no other keys" in validator_contract()
    for contract in (reasoner_contract(), validator_contract()):
        assert "no code fences, and no prose" in contract and "```" not in contract
        assert "ALWAYS a JSON array of strings" in contract and "ALWAYS a JSON number literal" in contract
    assert parse_intervention_response(reasoner_contract().rsplit("\n", 1)[1], {"EVID-001"})
    assert parse_solution_response(validator_contract().rsplit("\n", 1)[1])
    for name in ("training", "practice_simulation", "coaching", "process_correction", "investigate_further"):
        assert f'"{name}"' in REASONER_SYSTEM_PROMPT and f"- {name}:" in REASONER_PROMPT
    for fragment in ("do not re-diagnose", "they are the only references you may cite",
                     "never invent,\nguess, or paraphrase withheld comments", "it is a recommendation, not a decision",
                     "Training an agent to work around a flawed process\ndoes not correct a process gap"):
        assert fragment in REASONER_PROMPT, fragment
    for fragment in ("never propose, suggest, or imply a replacement diagnosis",
                     "never propose a replacement intervention", "do not penalize restraint",
                     "Never assert or imply human approval of the\nintervention", "a supported diagnosis\nwith a suitable intervention"):
        assert fragment in VALIDATOR_PROMPT, fragment
    for prompt in (REASONER_SYSTEM_PROMPT, VALIDATOR_SYSTEM_PROMPT):
        for forbidden in ("eval_", "ev_", "sig_", "Person One", "synthetic.xlsx"):
            assert forbidden not in prompt


def test_m5_decision_contract_extension_is_backward_compatible_and_consistent():
    service, _, _, _, signal = build()
    record = propose_and_validate(service)
    context = design_service(service, signal)._context("hyp_1")
    decision = decision_from_record(record, context)
    legacy = {k: v for k, v in decision.items() if k not in (
        "intervention_type", "target_change", "solution_alignment", "intervention_id", "solution_validation_id")}
    parsed = validate_decision(legacy, context)
    assert parsed.intervention_type is None and parsed.solution_alignment is None
    for mismatch in ({"decision_type": "non_training"}, {"intervention_type": "coaching"},
                     {"intervention_type": "investigate_further"}):
        with pytest.raises(ValidationError, match="disagree"):
            InterventionDecision.model_validate(decision | mismatch)
    with pytest.raises(ValidationError):
        InterventionDecision.model_validate(decision | {"solution_alignment": "approved"})
    assert InterventionDecision.model_validate(decision).intervention_type == "training"


def test_handoff_gate_is_a_lifecycle_projection():
    service, _, _, _, _ = build(None, {"intervention_type": "practice_simulation"},
                                {"alignment_outcome": "insufficient_evidence", "missing_information": ["Observation"]})
    proposed = asyncio.run(service.propose("hyp_1"))
    assert build_handoff(proposed.proposal, None).training_design_gate == "awaiting_solution_validation"
    record = asyncio.run(service.validate_solution("hyp_1"))
    assert record.status == "solution_questioned" and record.handoff.training_design_gate == "withheld"
    assert record.handoff.solution_status == "solution_questioned"
    assert json.loads(record.model_dump_json())["handoff"]["human_reviewed_intervention"] is False


def test_handoff_requires_proposal_and_validation_before_design():
    service, _, _, _, signal = build()
    designs = design_service(service, signal, ForbiddenTraining())
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.run("hyp_1"))
    assert error.value.code == "intervention_not_proposed"
    asyncio.run(service.propose("hyp_1"))
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.run("hyp_1"))
    assert error.value.code == "solution_not_validated"
    with pytest.raises(DesignError, match="No design run"):
        designs.get("hyp_1")
    asyncio.run(service.validate_solution("hyp_1"))
    designs.training = DemoDesignFixture(signal.signal_id)
    assert asyncio.run(designs.run("hyp_1")).training_design is not None


def test_demo_fixtures_pass_the_real_parsers_and_never_train_the_investigate_branch():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("m4demo", Path(__file__).resolve().parents[3] / "scripts" / "run_m4_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.fixture_evaluations()
    from app.diagnostics.engine import detect_signals
    resolution = next(s for s in detect_signals(rows) if s.criterion == "Resolution summary clarity")
    diagnosis = DiagnosticService(rows, module.DemoFixtureReasoner(resolution.signal_id))
    service = InterventionService(diagnosis, None, DemoInterventionFixture(), DemoSolutionFixture())
    designs = DesignService(diagnosis, ValidatedInterventionHandoff(service), DemoDesignFixture(resolution.signal_id),
                            controlled_fixture=True)
    for signal in detect_signals(rows):
        hypothesis_id = asyncio.run(diagnosis.diagnose(signal.signal_id)).provider_hypothesis.hypothesis_id
        diagnosis.approve(hypothesis_id, "demo")
        asyncio.run(service.propose(hypothesis_id))
        record = asyncio.run(service.validate_solution(hypothesis_id))
        result = asyncio.run(designs.run(hypothesis_id))
        if signal.signal_id == resolution.signal_id:
            assert record.proposal.intervention_type == "practice_simulation" and record.status == "solution_validated"
            assert result.training_design is not None
        else:
            assert record.proposal.intervention_type == "investigate_further"
            assert result.status == "evidence_required" and result.training_design is None


# --- API ----------------------------------------------------------------------------------------

def _install(service, signal, training=None):
    prior = (app.state.diagnostics, app.state.interventions, app.state.designs)
    app.state.diagnostics = service.diagnostics
    app.state.interventions = service
    app.state.designs = design_service(service, signal, training)
    return prior


def _restore(prior):
    app.state.diagnostics, app.state.interventions, app.state.designs = prior


def test_api_stages_read_paths_and_precondition_codes():
    service, _, _, _, signal = build()
    prior = _install(service, signal, ForbiddenTraining())
    try:
        client = TestClient(app)
        assert client.get("/interventions/diagnoses/missing").status_code == 404
        assert client.get("/interventions/diagnoses/hyp_1").json()["detail"]["code"] == "intervention_not_found"
        assert client.post("/interventions/diagnoses/hyp_1/validate-solution").status_code == 404
        design = client.post("/designs/diagnoses/hyp_1")
        assert design.status_code == 409 and design.json()["detail"]["code"] == "intervention_not_proposed"
        proposed = client.post("/interventions/diagnoses/hyp_1/propose")
        assert proposed.status_code == 200 and proposed.json()["status"] == "intervention_proposed"
        assert proposed.json()["handoff"]["training_design_gate"] == "awaiting_solution_validation"
        assert client.get("/interventions/diagnoses/hyp_1").json() == proposed.json()
        assert client.post("/interventions/diagnoses/hyp_1/propose").json() == proposed.json()
        design = client.post("/designs/diagnoses/hyp_1")
        assert design.status_code == 409 and design.json()["detail"]["code"] == "solution_not_validated"
        validated = client.post("/interventions/diagnoses/hyp_1/validate-solution")
        assert validated.status_code == 200 and validated.json()["status"] == "solution_validated"
        assert validated.json()["solution_validation"]["alignment_outcome"] == "aligned"
        assert client.get("/interventions/diagnoses/hyp_1").json() == validated.json()
        assert client.get("/diagnostics/hypotheses/hyp_1").json()["status"] == "approved"
        mode = client.get("/diagnostics/mode").json()
        assert mode["intervention_provider"] == "controlled_fixture" and mode["solution_validator"] == "controlled_fixture"
        assert mode["design_provider"] == "controlled_fixture"
    finally:
        _restore(prior)


def test_api_refuses_unapproved_unavailable_and_malformed_without_provider_text():
    source, signal, bundle = prepared()
    unapproved = DiagnosticService(source, ControlledTestReasoner(diagnostic_response(bundle)))
    asyncio.run(unapproved.diagnose(signal.signal_id))
    service = InterventionService(unapproved, None, UnavailableInterventionReasoner(), UnavailableSolutionValidator())
    prior = _install(service, signal)
    try:
        client = TestClient(app)
        blocked = client.post("/interventions/diagnoses/hyp_1/propose")
        assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "diagnosis_not_approved"
        unapproved.approve("hyp_1", "lead")
        unavailable = client.post("/interventions/diagnoses/hyp_1/propose")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "intervention_provider_unavailable"

        class Leaky:
            async def propose(self, request):
                raise RuntimeError("secret provider detail")

        service.reasoner = Leaky()
        failed = client.post("/interventions/diagnoses/hyp_1/propose")
        assert failed.status_code == 502 and "secret" not in failed.text
        assert failed.json()["detail"] == {"code": "intervention_provider_failure",
                                           "message": "Intervention reasoner failed"}
        service.reasoner = ControlledInterventionReasoner(intervention_response(intervention_type="guess"))
        malformed = client.post("/interventions/diagnoses/hyp_1/propose")
        assert malformed.status_code == 502 and malformed.json()["detail"]["code"] == "invalid_intervention_output"
        assert client.get("/interventions/diagnoses/hyp_1").status_code == 404
        service.reasoner = ControlledInterventionReasoner(intervention_response())
        assert client.post("/interventions/diagnoses/hyp_1/propose").status_code == 200
        unavailable = client.post("/interventions/diagnoses/hyp_1/validate-solution")
        assert unavailable.status_code == 503 and unavailable.json()["detail"]["code"] == "solution_validator_unavailable"
        service.validator = ControlledSolutionValidator(solution_response(alignment_outcome="misaligned", aligned_points=[],
                                                                          misaligned_points=["Does not fit"]))
        assert client.post("/interventions/diagnoses/hyp_1/validate-solution").json()["status"] == "solution_questioned"
        withheld = client.post("/designs/diagnoses/hyp_1")
        assert withheld.status_code == 409 and withheld.json()["detail"]["code"] == "training_design_withheld"
        assert "questioned the proposed training" in withheld.json()["detail"]["message"]
    finally:
        _restore(prior)


def test_context_builder_requires_approval_and_verifies_the_population():
    diagnosis, _, _, _ = approved_diagnosis()
    context = build_intervention_context(diagnosis, "hyp_1")
    assert context.allowed_refs == frozenset({"EVID-001"})
    assert context.request["human_validation"] == {"human_revised": False, "revision_rationale": None}
    source, signal, bundle = prepared()
    pending = DiagnosticService(source, ControlledTestReasoner(diagnostic_response(bundle)))
    asyncio.run(pending.diagnose(signal.signal_id))
    with pytest.raises(DiagnosticError) as error:
        build_intervention_context(pending, "hyp_1")
    assert error.value.code == "diagnosis_not_approved"
    with diagnosis._lock:
        diagnosis._provider_snapshots["hyp_1"][0]["evidence_items"][0]["criterion"] = "tampered"
    with pytest.raises(DiagnosticError) as error:
        build_intervention_context(diagnosis, "hyp_1")
    assert error.value.code == "evidence_mismatch"


def test_record_json_is_a_complete_audit_trail():
    service, _, _, _, _ = build(evidence_review=evidence_review())
    record = propose_and_validate(service)
    payload = json.loads(record.model_dump_json())
    InterventionRecord.model_validate(payload)
    assert set(payload) == {"hypothesis_id", "signal_id", "validated_diagnosis", "diagnosis_digest",
                            "evidence_review_status", "semantic_review", "status", "proposal",
                            "solution_validation", "handoff", "created_at", "updated_at"}
    assert payload["validated_diagnosis"]["approved_by"] == "lead" and payload["validated_diagnosis"]["approved_at"]
    assert payload["semantic_review"]["semantic_status"] == "evidence_validated"
    assert payload["proposal"]["provider_metadata"]["generation_mode"] == "controlled_fixture"
    assert payload["proposal"]["created_at"] and payload["solution_validation"]["created_at"]
    assert payload["proposal"]["evidence_refs"][0]["item_id"].startswith("ev_")
    assert payload["handoff"]["decision_type"] == "training"
    copy = deepcopy(payload)
    copy["proposal"]["rationale"] = "tampered"
    assert service.get("hyp_1").proposal.rationale != "tampered"
