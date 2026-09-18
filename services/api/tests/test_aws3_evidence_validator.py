"""AWS-3 contracts use generated evidence and mocked Converse; no live AWS calls."""

import asyncio
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from app.diagnostics.bedrock import BedrockReasoner
from app.diagnostics.engine import ControlledTestReasoner, DiagnosticError, DiagnosticService, ProviderOutputError
from app.diagnostics.evidence_validator import (FIELD_GUIDANCE, PROMPT, SYSTEM_PROMPT, BedrockEvidenceValidator,
                                                ControlledTestEvidenceValidator, EvidenceValidationService,
                                                UnavailableEvidenceValidator, ValidatorResponse,
                                                _sensitive_diagnosis_text, build_validation_request,
                                                parse_validator_response, response_contract)
from app.diagnostics.models import EvidenceReference
from app.main import app
from app.results_cx import demo
from app.results_cx.demo import install_results_cx_demo
from test_bedrock import FakeRuntime, synthetic_reasoner
from test_diagnostics import evaluations, prepared, response as diagnostic_response
from test_results_cx_demo import generated_sources


def validator_response(**changes):
    return {"validation_outcome": "supported", "support_assessment": "The observed pattern is supported; cause remains unknown.",
            "supported_reference_ids": ["EVID-001"], "contradicting_reference_ids": [],
            "unsupported_claims": [], "missing_evidence": ["Direct workflow observation"],
            "provider_reported_confidence": 0.7} | changes


def fixture_service(diagnosis_changes=None, validation_changes=None):
    rows, signal, bundle = prepared()
    diagnosis = DiagnosticService(rows, ControlledTestReasoner(
        diagnostic_response(bundle, **(diagnosis_changes or {}))))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    validator = ControlledTestEvidenceValidator(validator_response(**(validation_changes or {})))
    return diagnosis, EvidenceValidationService(diagnosis, validator), validator, bundle


def test_validation_record_is_idempotent_and_human_review_remains_consequential():
    diagnosis, service, validator, bundle = fixture_service()
    first = asyncio.run(service.run("hyp_1"))
    second = asyncio.run(service.run("hyp_1"))
    assert first == second and len(validator.requests) == 1
    assert first.hypothesis_id == "hyp_1" and first.signal_id == bundle.signal.signal_id
    assert first.semantic_status == "evidence_validated"
    assert first.validation_id.startswith("val_") and first.provider_metadata.generation_mode == "controlled_fixture"
    assert diagnosis.get("hyp_1").status == "awaiting_review"
    with pytest.raises(DiagnosticError, match="not been approved"):
        diagnosis.get_approved_diagnosis("hyp_1")
    diagnosis.approve("hyp_1", "reviewer")
    assert diagnosis.get_approved_diagnosis("hyp_1").hypothesis_id == "hyp_1"
    assert service.get("hyp_1") == first
    assert service.get("hyp_1").hypothesis_id != "another"


@pytest.mark.parametrize(("outcome", "action"), [
    ("unsupported", "approve"), ("insufficient_evidence", "reject"),
    ("partially_supported", "revise")])
def test_questioned_outcomes_remain_open_to_human_review(outcome, action):
    diagnosis, service, _, _ = fixture_service(validation_changes={
        "validation_outcome": outcome, "unsupported_claims": ["The cause is asserted, not shown"]})
    assert asyncio.run(service.run("hyp_1")).validation_outcome == outcome
    assert service.get("hyp_1").semantic_status == "evidence_questioned"
    assert diagnosis.get("hyp_1").status == "awaiting_review"
    if action == "approve":
        diagnosis.approve("hyp_1", "reviewer")
        assert diagnosis.get("hyp_1").status == "approved"
    elif action == "reject":
        diagnosis.reject("hyp_1", "reviewer", "Reviewed evidence")
        assert diagnosis.get("hyp_1").status == "rejected"
    else:
        hypothesis = diagnosis.get("hyp_1").provider_hypothesis
        revision = {key: getattr(hypothesis, key) for key in (
            "observed_behavioral_defect", "cause_domain", "performance_dimension", "explanation",
            "supporting_evidence", "conflicting_evidence", "missing_evidence")}
        diagnosis.revise("hyp_1", "reviewer", revision, "Reviewed evidence")
        assert diagnosis.get("hyp_1").status == "revised"


def test_request_contains_uncited_contradiction_and_no_local_fields():
    diagnosis, service, validator, bundle = fixture_service()
    asyncio.run(service.run("hyp_1"))
    request = validator.requests[0]
    assert len(request["evidence_items"]) == 2
    assert request["citation_roles"] == {"supporting_reference_ids": ["EVID-001"],
                                          "conflicting_reference_ids": []}
    assert request["evidence_items"][1]["reference"] == "EVID-002"
    wire = json.dumps(request)
    for forbidden in ("Person One", "Reviewer One", "Lead One", "eval_1", "ev_", "sig_",
                      "synthetic.xlsx", "Sheet", "source_lineage", "evaluator_feedback",
                      "answer", "evaluation_id", "item_id", "agent_name", "qa_name"):
        assert forbidden not in wire


def test_uncited_passing_evidence_can_be_reported_as_contradicting():
    rows = evaluations()
    rows[1].criteria[0].passed = True
    rows[1].criteria[0].attained_score = rows[1].criteria[0].max_score
    diagnosis = DiagnosticService(rows, ControlledTestReasoner({}))
    signal = next(s for s in diagnosis.list_signals() if s.criterion == "Greeting")
    bundle = diagnosis.evidence(signal.signal_id)
    diagnosis.reasoner.response = diagnostic_response(bundle)
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    validator = ControlledTestEvidenceValidator(validator_response(
        validation_outcome="partially_supported", contradicting_reference_ids=["EVID-002"],
        support_assessment="Passing evidence weakens a broad failure claim."))
    service = EvidenceValidationService(diagnosis, validator)
    result = asyncio.run(service.run("hyp_1"))
    assert result.contradicting_reference_ids == ("EVID-002",)
    assert validator.requests[0]["evidence_items"][1]["failed"] is False
    assert validator.requests[0]["citation_roles"]["conflicting_reference_ids"] == []


@pytest.mark.parametrize("change", [
    {"supported_reference_ids": ["EVID-999"]},
    {"supported_reference_ids": ["EVID-001", "EVID-001"]},
    {"supported_reference_ids": ["EVID-001"], "contradicting_reference_ids": ["EVID-001"]},
    {"validation_outcome": "certain"},
    {"provider_reported_confidence": "0.5"},
    {"provider_reported_confidence": "low"},
    {"provider_reported_confidence": 1.1},
    {"provider": "Amazon Bedrock"},
    {"model": "forged-model"},
    {"generation_mode": "provider"},
    {"hypothesis_id": "hyp_1"},
    {"signal_id": "sig_1"},
    {"cause_domain": "knowledge_gap"},
    {"unsupported_claims": "one claim"},
    {"unsupported_claims": [" "]},
])
def test_malformed_semantic_output_fails_closed(change):
    diagnosis, service, _, _ = fixture_service(validation_changes=change)
    with pytest.raises(ProviderOutputError) as error:
        asyncio.run(service.run("hyp_1"))
    assert error.value.code == "invalid_validator_output"
    with pytest.raises(DiagnosticError) as absent:
        service.get("hyp_1")
    assert absent.value.code == "validation_not_found"


@pytest.mark.parametrize("text", ["not json", "```json\n{}\n```", json.dumps(validator_response()) + " extra"])
def test_json_parser_rejects_non_object_document(text):
    with pytest.raises(ProviderOutputError):
        parse_validator_response(text, {"EVID-001"})


def test_prechecks_block_forged_and_cross_signal_citations_before_validator():
    diagnosis, service, validator, bundle = fixture_service()
    with diagnosis._lock:
        original = diagnosis._records["hyp_1"].provider_hypothesis
        forged = original.model_copy(update={"supporting_evidence": [
            original.supporting_evidence[0].model_copy(update={"item_id": "ev_invented"})]})
        diagnosis._records["hyp_1"].provider_hypothesis = forged
    with pytest.raises(DiagnosticError) as error:
        asyncio.run(service.run("hyp_1"))
    assert error.value.code == "invalid_evidence_reference" and not validator.requests
    other = next(s for s in diagnosis.list_signals() if s.signal_id != bundle.signal.signal_id)
    cross = diagnosis.evidence(other.signal_id).items[0]
    with diagnosis._lock:
        diagnosis._records["hyp_1"].provider_hypothesis = original.model_copy(update={
            "supporting_evidence": [original.supporting_evidence[0].model_copy(update={
                "item_id": cross.item_id, "evaluation_id": cross.evaluation_id})]})
    with pytest.raises(DiagnosticError):
        asyncio.run(service.run("hyp_1"))
    assert not validator.requests


def test_mutated_provider_population_and_local_comment_in_diagnosis_block_wire():
    diagnosis, service, validator, _ = fixture_service()
    with diagnosis._lock:
        diagnosis._provider_snapshots["hyp_1"][0]["evidence_items"][0]["criterion"] = "tampered"
    with pytest.raises(DiagnosticError):
        asyncio.run(service.run("hyp_1"))
    assert not validator.requests
    diagnosis, service, validator, _ = fixture_service({"explanation": "Person One missed greeting"})
    with pytest.raises(DiagnosticError) as error:
        asyncio.run(service.run("hyp_1"))
    assert error.value.code == "provider_privacy_blocked" and not validator.requests


def test_provider_failure_non_end_turn_and_no_fallback():
    rows = evaluations()
    runtime = FakeRuntime()
    diagnosis = DiagnosticService(rows, synthetic_reasoner(rows, runtime))
    hypothesis = asyncio.run(diagnosis.diagnose(diagnosis.list_signals()[0].signal_id)).provider_hypothesis
    for validator_runtime in (FakeRuntime(error=RuntimeError("secret")),
                              FakeRuntime(text=json.dumps(validator_response()), stop_reason="max_tokens"),
                              FakeRuntime(text="```json\n{}\n```")):
        service = EvidenceValidationService(diagnosis, BedrockEvidenceValidator(client=validator_runtime))
        with pytest.raises(ProviderOutputError):
            asyncio.run(service.run(hypothesis.hypothesis_id))
        with pytest.raises(DiagnosticError):
            service.get(hypothesis.hypothesis_id)
        assert len(validator_runtime.calls) == 1


def test_bedrock_success_stamps_provenance_locally_and_uses_separate_prompt():
    rows = evaluations()
    reasoning_runtime = FakeRuntime()
    diagnosis = DiagnosticService(rows, synthetic_reasoner(rows, reasoning_runtime))
    hypothesis = asyncio.run(diagnosis.diagnose(diagnosis.list_signals()[0].signal_id)).provider_hypothesis
    runtime = FakeRuntime(text=json.dumps(validator_response()))
    service = EvidenceValidationService(diagnosis, BedrockEvidenceValidator(client=runtime))
    record = asyncio.run(service.run(hypothesis.hypothesis_id))
    assert record.provider_metadata.provider == "Amazon Bedrock"
    assert record.provider_metadata.model == "global.anthropic.claude-sonnet-4-6"
    assert record.provider_metadata.invocation_region == "us-east-1"
    assert record.provider_metadata.generation_mode == "provider"
    assert runtime.calls[0]["system"] != reasoning_runtime.calls[0]["system"]
    assert runtime.calls[0]["modelId"] == reasoning_runtime.calls[0]["modelId"]
    assert diagnosis.get(hypothesis.hypothesis_id).status == "awaiting_review"


def test_real_structured_only_validator_wire_and_coverage(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    reasoning_runtime = FakeRuntime()
    reasoner = BedrockReasoner.for_trusted_results_cx("us-east-1", "global.anthropic.claude-sonnet-4-6",
                                                      trusted, client=reasoning_runtime)
    diagnosis = DiagnosticService(trusted, reasoner)
    hypothesis = asyncio.run(diagnosis.diagnose(diagnosis.list_signals()[0].signal_id)).provider_hypothesis
    runtime = FakeRuntime(text=json.dumps(validator_response()))
    service = EvidenceValidationService(diagnosis, BedrockEvidenceValidator(client=runtime))
    record = asyncio.run(service.run(hypothesis.hypothesis_id))
    assert record.validation_outcome == "supported"
    request = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
    original = json.loads(reasoning_runtime.calls[0]["messages"][0]["content"][0]["text"])
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
    assert "diagnostic_text" not in json.dumps(request)
    for forbidden in ("Synthetic note", "minimized_evaluator_feedback", "eval_",
                      "ev_", "sig_", "source_lineage", "source_filename", "source_sheet",
                      "agent_name", "qa_name", "team_leader", "internal_id"):
        assert forbidden not in serialized


def test_unavailable_and_reviewed_states_fail_without_storage():
    diagnosis, _, _, _ = fixture_service()
    unavailable = EvidenceValidationService(diagnosis, UnavailableEvidenceValidator())
    with pytest.raises(DiagnosticError) as error:
        asyncio.run(unavailable.run("hyp_1"))
    assert error.value.code == "validator_unavailable"
    diagnosis.approve("hyp_1", "reviewer")
    with pytest.raises(DiagnosticError) as error:
        asyncio.run(unavailable.run("hyp_1"))
    assert error.value.code == "invalid_state_transition"


@pytest.mark.parametrize(("diagnosis_changes", "validation_changes", "expected"), [
    ({"cause_domain": "knowledge_gap", "explanation": "Failure frequency proves missing knowledge.",
      "missing_evidence": []},
     {"validation_outcome": "insufficient_evidence", "supported_reference_ids": [],
      "unsupported_claims": ["Frequency proves a knowledge gap"]}, "insufficient_evidence"),
    ({}, {"validation_outcome": "supported", "support_assessment":
          "Failures are observed; the undetermined cause is appropriately restrained."}, "supported"),
    ({}, {"validation_outcome": "partially_supported", "contradicting_reference_ids": ["EVID-002"],
          "support_assessment": "An uncited passing example weakens the broad claim."}, "partially_supported"),
    ({"explanation": "An evaluator said coaching was absent."},
     {"validation_outcome": "unsupported", "unsupported_claims":
      ["No evaluator statement was supplied"]}, "unsupported"),
    ({"missing_evidence": ["Direct workflow observation"]},
     {"validation_outcome": "supported", "missing_evidence": ["Direct workflow observation"]}, "supported"),
])
def test_adversarial_semantic_provider_contracts(diagnosis_changes, validation_changes, expected):
    diagnosis, service, validator, _ = fixture_service(diagnosis_changes, validation_changes)
    result = asyncio.run(service.run("hyp_1"))
    assert result.validation_outcome == expected
    assert validator.requests[0]["proposed_diagnosis"]["explanation"] == diagnosis.get("hyp_1").provider_hypothesis.explanation
    assert diagnosis.get("hyp_1").status == "awaiting_review"


def test_api_validation_read_and_human_approval_paths():
    diagnosis, service, _, bundle = fixture_service()
    original = app.state.diagnostics, app.state.evidence_validations
    app.state.diagnostics, app.state.evidence_validations = diagnosis, service
    try:
        client = TestClient(app)
        assert client.get("/diagnostics/hypotheses/missing/evidence-validation").status_code == 404
        created = client.post("/diagnostics/hypotheses/hyp_1/validate-evidence")
        assert created.status_code == 200
        assert created.json()["signal_id"] == bundle.signal.signal_id
        assert client.get("/diagnostics/hypotheses/hyp_1/evidence-validation").json() == created.json()
        assert client.get("/diagnostics/hypotheses/hyp_1").json()["status"] == "awaiting_review"
        assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "reviewer"}).status_code == 200
    finally:
        app.state.diagnostics, app.state.evidence_validations = original


@pytest.mark.parametrize("change", [
    {"validation_outcome": "supported", "supported_reference_ids": []},
    {"validation_outcome": "partially_supported", "supported_reference_ids": []},
    {"validation_outcome": "unsupported", "unsupported_claims": [], "contradicting_reference_ids": []},
    {"validation_outcome": "insufficient_evidence", "missing_evidence": []},
])
def test_incoherent_outcomes_fail_closed_without_repair(change):
    """An outcome must name what grounds it; the service never fills the gap for the model."""
    diagnosis, service, validator, _ = fixture_service(validation_changes=change)
    with pytest.raises(ProviderOutputError) as error:
        asyncio.run(service.run("hyp_1"))
    assert error.value.code == "invalid_validator_output" and len(validator.requests) == 1
    with pytest.raises(DiagnosticError):
        service.get("hyp_1")


def test_record_resolves_provider_references_to_local_evidence():
    diagnosis, service, _, bundle = fixture_service(validation_changes={
        "validation_outcome": "partially_supported", "supported_reference_ids": ["SIGNAL-001", "EVID-001"],
        "contradicting_reference_ids": ["EVID-002"]})
    record = asyncio.run(service.run("hyp_1"))
    assert record.supported_reference_ids == ("SIGNAL-001", "EVID-001")
    assert record.supported_evidence == (
        EvidenceReference(item_id="signal", evaluation_id=None),
        EvidenceReference(item_id=bundle.items[0].item_id, evaluation_id=bundle.items[0].evaluation_id))
    assert record.contradicting_evidence == (
        EvidenceReference(item_id=bundle.items[1].item_id, evaluation_id=bundle.items[1].evaluation_id),)
    assert record.assessed_proposal == "provider_hypothesis"
    # The wire request never carried the local IDs that the record resolves to.
    assert bundle.items[0].item_id not in json.dumps(service.validator.requests[0])


def test_human_revision_does_not_inherit_or_rerun_the_semantic_review():
    diagnosis, service, validator, bundle = fixture_service(validation_changes={
        "validation_outcome": "unsupported", "unsupported_claims": ["Cause not shown"]})
    original = asyncio.run(service.run("hyp_1"))
    hypothesis = diagnosis.get("hyp_1").provider_hypothesis
    revision = {"observed_behavioral_defect": hypothesis.observed_behavioral_defect,
                "cause_domain": "process_gap", "performance_dimension": "undetermined",
                "explanation": "Reviewer attributes the pattern to a documented workflow change.",
                "supporting_evidence": [{"item_id": bundle.items[0].item_id,
                                         "evaluation_id": bundle.items[0].evaluation_id}],
                "conflicting_evidence": [], "missing_evidence": []}
    revised = diagnosis.revise("hyp_1", "reviewer", revision, "Reviewed the workflow")
    assert revised.status == "revised" and revised.human_revision.cause_domain == "process_gap"
    # The stored review still describes the provider proposal only, and a repeat request
    # returns that record without another provider call rather than re-reviewing the revision.
    after = asyncio.run(service.run("hyp_1"))
    assert after == original and after.assessed_proposal == "provider_hypothesis"
    assert after.validation_outcome == "unsupported" and len(validator.requests) == 1
    assert service.get("hyp_1").hypothesis_id == "hyp_1"


def test_real_demo_install_binds_validator_to_installed_diagnostics(tmp_path):
    """The real ResultsCX demo replaces the diagnostic service; the validator must follow it."""
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    original = app.state.diagnostics, app.state.evidence_validations, app.state.designs, app.state.demo_mode
    try:
        install_results_cx_demo(app, trusted)
        assert app.state.evidence_validations.diagnostics is app.state.diagnostics
        assert isinstance(app.state.evidence_validations.validator, UnavailableEvidenceValidator)
        client = TestClient(app)
        signal_id = app.state.diagnostics.list_signals()[0].signal_id
        app.state.diagnostics.reasoner = ControlledTestReasoner({})
        bundle = app.state.diagnostics.evidence(signal_id)
        app.state.diagnostics.reasoner.response = diagnostic_response(bundle, signal_id=signal_id)
        created = client.post(f"/diagnostics/signals/{signal_id}/hypotheses").json()
        hypothesis_id = created["provider_hypothesis"]["hypothesis_id"]
        # A hypothesis produced by the installed service is found; only the validator is absent.
        response = client.post(f"/diagnostics/hypotheses/{hypothesis_id}/validate-evidence")
        assert response.status_code == 503 and response.json()["detail"]["code"] == "validator_unavailable"
    finally:
        (app.state.diagnostics, app.state.evidence_validations, app.state.designs,
         app.state.demo_mode) = original


def test_privacy_screen_matches_identifiers_as_words_and_only_long_verbatim_comments():
    rows = evaluations()
    rows[0].agent_name = "Ana"
    rows[0].criteria[0].lineage.source_sheet = "QA"
    rows[0].criteria[0].evaluator_feedback = "Missed greeting"
    rows[1].criteria[0].evaluator_feedback = "Agent skipped the required greeting and did not verify the caller"
    diagnosis = DiagnosticService(rows, ControlledTestReasoner({}))
    # Ordinary diagnostic prose that merely contains a short comment or a name/sheet substring.
    assert not _sensitive_diagnosis_text(diagnosis, [
        "The analysis of QA rows shows the agent missed greeting steps on two calls."])
    # Whole-word identity, local ID, and a long verbatim comment still stop the second trip.
    assert _sensitive_diagnosis_text(diagnosis, ["Ana missed the greeting."])
    assert _sensitive_diagnosis_text(diagnosis, ["See eval_1 for context."])
    assert _sensitive_diagnosis_text(diagnosis, [
        "An evaluator wrote: agent skipped the required greeting and did not verify the caller."])


def test_validator_prompt_states_the_resultscx_reasoning_rubric():
    for fragment in (
        "does the supplied evidence support the proposed diagnosis",
        "Never create, suggest, or imply a replacement diagnosis",
        "proves what happened, not why",
        "does not establish a knowledge, skill, process,\ncoaching, or training cause",
        "uncited passing evidence weaken a broad claim",
        "Missing qualitative evidence matters",
        "Never\ninvent, guess, or paraphrase withheld comments",
        "evaluator statements, observations, or comments that were not supplied as unsupported",
        "do not penalize restraint",
        "claim stronger than the evidence permits",
        "Never\nassert or imply human approval",
        "evaluations_containing_criterion",
    ):
        assert fragment in PROMPT, fragment
    assert SYSTEM_PROMPT == PROMPT + "\n\n" + response_contract()
    assert set(FIELD_GUIDANCE) == set(ValidatorResponse.model_fields)
    for name in ValidatorResponse.model_fields:
        assert f'"{name}"' in SYSTEM_PROMPT
    assert "training" not in SYSTEM_PROMPT.split("Outcomes.")[1]  # the validator never recommends it
    for forbidden in ("eval_", "ev_", "sig_", "Person One", "synthetic.xlsx"):
        assert forbidden not in SYSTEM_PROMPT


def _request_for(diagnosis_changes=None, validation_changes=None, rows=None):
    if rows is None:
        diagnosis, service, validator, bundle = fixture_service(diagnosis_changes, validation_changes)
    else:
        diagnosis = DiagnosticService(rows, ControlledTestReasoner({}))
        signal = next(s for s in diagnosis.list_signals() if s.criterion == "Greeting")
        bundle = diagnosis.evidence(signal.signal_id)
        diagnosis.reasoner.response = diagnostic_response(bundle, **(diagnosis_changes or {}))
        asyncio.run(diagnosis.diagnose(signal.signal_id))
        validator = ControlledTestEvidenceValidator(validator_response(**(validation_changes or {})))
        service = EvidenceValidationService(diagnosis, validator)
    record = asyncio.run(service.run("hyp_1"))
    return record, validator.requests[0], diagnosis


def test_case_a_frequency_alone_knowledge_gap_claim_is_questioned_with_the_facts_in_view():
    record, request, diagnosis = _request_for(
        {"cause_domain": "knowledge_gap", "performance_dimension": "capability",
         "explanation": "A 100% failure rate proves the agents lack product knowledge.",
         "missing_evidence": [], "provider_reported_confidence": "0.9"},
        {"validation_outcome": "partially_supported", "supported_reference_ids": ["SIGNAL-001"],
         "unsupported_claims": ["A 100% failure rate proves a knowledge gap"],
         "missing_evidence": ["Evaluator comments describing what the agent said"],
         "provider_reported_confidence": 0.25})
    # The validator receives the causal claim, its confidence, and the aggregate facts it rests on.
    proposal = request["proposed_diagnosis"]
    assert proposal["cause_domain"] == "knowledge_gap" and proposal["provider_reported_confidence"] == 0.9
    assert request["signal"]["failure_rate"] == "1" and request["signal"]["failed_criterion_result_count"] == 2
    assert record.semantic_status == "evidence_questioned" and record.unsupported_claims
    assert diagnosis.get("hyp_1").status == "awaiting_review"


def test_case_b_restrained_undetermined_proposal_can_be_supported():
    record, request, _ = _request_for(
        None, {"validation_outcome": "supported", "supported_reference_ids": ["SIGNAL-001", "EVID-001"],
               "support_assessment": "The observed defect is established; the undetermined cause is honest."})
    assert request["proposed_diagnosis"]["cause_domain"] == "undetermined"
    assert request["proposed_diagnosis"]["missing_evidence"] == ["Ask reviewer for context"]
    assert record.semantic_status == "evidence_validated"


def test_case_c_uncited_passing_evidence_is_visible_and_can_contradict():
    rows = evaluations()
    rows[1].criteria[0].passed = True
    rows[1].criteria[0].attained_score = rows[1].criteria[0].max_score
    record, request, _ = _request_for(
        {"cause_domain": "skill_gap", "performance_dimension": "capability",
         "explanation": "Every greeting fails, so the agents cannot perform the greeting."},
        {"validation_outcome": "unsupported", "contradicting_reference_ids": ["EVID-002"],
         "unsupported_claims": ["Every greeting fails"]}, rows=rows)
    # The proposal cited only EVID-001; the passing EVID-002 is in the population but uncited.
    assert request["citation_roles"] == {"supporting_reference_ids": ["EVID-001"], "conflicting_reference_ids": []}
    assert [item["failed"] for item in request["evidence_items"]] == [True, False]
    assert record.contradicting_reference_ids == ("EVID-002",)
    assert record.contradicting_evidence[0].evaluation_id == "eval_2"


def test_case_d_claimed_evaluator_evidence_was_never_supplied():
    record, request, _ = _request_for(
        {"explanation": "The evaluator commented that the agent skipped the script."},
        {"validation_outcome": "unsupported", "unsupported_claims": ["An evaluator comment is quoted but none was supplied"]})
    # No comment text reaches the validator, and coverage says the local comment was withheld.
    assert "diagnostic_text" not in json.dumps(request["evidence_items"])
    assert request["text_coverage"]["evidence_items_with_feedback"] == 1
    assert request["text_coverage"]["text_items_blocked"] == 1
    assert request["text_coverage"]["minimized_text_items_allowed"] == 0
    assert "missed greeting" not in json.dumps(request).casefold()
    assert record.validation_outcome == "unsupported"


def test_case_e_acknowledged_gaps_reach_the_validator_and_are_recorded():
    record, request, _ = _request_for(
        {"missing_evidence": ["Call recordings", "Evaluator comments"]},
        {"validation_outcome": "supported", "missing_evidence": ["Call recordings"]})
    assert request["proposed_diagnosis"]["missing_evidence"] == ["Call recordings", "Evaluator comments"]
    assert record.missing_evidence == ("Call recordings",)


def test_case_f_cited_conflicting_evidence_is_carried_as_a_role_not_removed():
    rows = evaluations()
    rows[1].criteria[0].passed = True
    rows[1].criteria[0].attained_score = rows[1].criteria[0].max_score
    diagnosis = DiagnosticService(rows, ControlledTestReasoner({}))
    signal = next(s for s in diagnosis.list_signals() if s.criterion == "Greeting")
    bundle = diagnosis.evidence(signal.signal_id)
    passing = bundle.items[1]
    diagnosis.reasoner.response = diagnostic_response(
        bundle, conflicting_evidence=[{"item_id": passing.item_id, "evaluation_id": passing.evaluation_id}])
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    validator = ControlledTestEvidenceValidator(validator_response(
        validation_outcome="partially_supported", contradicting_reference_ids=["EVID-002"],
        support_assessment="The cited passing evaluation limits the claim to one evaluation."))
    record = asyncio.run(EvidenceValidationService(diagnosis, validator).run("hyp_1"))
    assert validator.requests[0]["citation_roles"]["conflicting_reference_ids"] == ["EVID-002"]
    assert record.contradicting_reference_ids == ("EVID-002",) and record.semantic_status == "evidence_questioned"
