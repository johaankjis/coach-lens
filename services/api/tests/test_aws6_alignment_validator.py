"""AWS-6 Independent Training Alignment Validator tests. Synthetic QA rows, controlled AWS-4
fixtures, a fake Converse runtime for AWS-5 and AWS-6, no AWS.

Case labels (A-R) follow the AWS-6 milestone test list. Every reviewed package here was
stored by the real chain: human-approved diagnosis -> AWS-4 (controlled fixtures) ->
`ValidatedInterventionHandoff` -> `BedrockTrainingDesigner` (fake runtime) -> `DesignService`.
The alignment validator is either a controlled fixture (semantic verdict supplied by the test)
or the Bedrock adapter over the same fake runtime (contract, provenance, and privacy tests).
"""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.design.alignment_bedrock import (SYSTEM_PROMPT, BedrockAlignmentValidator, converse_text,
                                          response_contract)
from app.design.alignment_review import (DIMENSIONS, ERROR_MESSAGES, GAP_KEYS, INTERVENTION_KEYS,
                                         PACKAGE_KEYS, REQUEST_KEYS, AlignmentOutputError, AlignmentResponse,
                                         AlignmentReview, AlignmentReviewError, build_alignment_view,
                                         design_digest, design_status_for, parse_alignment_response)
from app.design.alignment_service import (AlignmentReviewService, ControlledAlignmentValidator,
                                          UnavailableAlignmentValidator, alignment_provider_kind)
from app.design.service import DesignError
from app.diagnostics.bedrock import BedrockReasoner
from app.diagnostics.engine import DiagnosticService
from app.main import app
from app.pipeline import build_pipeline, install_pipeline
from test_aws5_training_designer import FakeRuntime, _fixture_service, package, run, setup
from test_diagnostics import prepared


# --- Fixtures ---------------------------------------------------------------------------

def dimension(outcome="aligned", ids=(), assessment="The downstream element supports the upstream need."):
    return {"outcome": outcome, "assessment": assessment, "misaligned_element_ids": list(ids)}


def alignment_response(overall="aligned", *, unsupported=(), missing=(), confidence=0.8, **dimensions):
    """A coherent AWS-6 verdict. Keyword arguments override individual dimensions."""
    dims = {name: dimension() for name in DIMENSIONS} | dimensions
    return {"overall_outcome": overall,
            "overall_assessment": "The package trains the confirmed closing-sequence behavior.",
            "dimensions": dims, "unsupported_assumptions": list(unsupported),
            "missing_information": list(missing), "provider_reported_confidence": confidence}


def questioned(name, ids, overall="misaligned"):
    return alignment_response(overall, **{name: dimension("misaligned", ids, "Drifts from the upstream need.")})


def reviewed(response=None, *, package_text=None, validator=None, bedrock=False, **setup_changes):
    """A stored provider-backed AWS-5 package plus an AWS-6 service over it."""
    runtime = FakeRuntime(json.dumps(package_text) if package_text is not None else None)
    service, _, _, interventions = setup(runtime=runtime, **setup_changes)
    result = run(service)
    if validator is None:
        text = json.dumps(alignment_response() if response is None else response)
        validator = (BedrockAlignmentValidator(client=FakeRuntime(text), diagnostics=service.diagnostics)
                     if bedrock else ControlledAlignmentValidator(json.loads(text)))
    return AlignmentReviewService(service, validator), validator, service, result, interventions


def review(svc):
    return asyncio.run(svc.review("hyp_1"))


def refused(svc, code="invalid_alignment_output"):
    with pytest.raises(DesignError) as failure:
        review(svc)
    assert failure.value.code == code and str(failure.value) == ERROR_MESSAGES[code]
    with pytest.raises(DesignError) as missing:
        svc.get("hyp_1")
    assert missing.value.code == "alignment_review_not_found"
    return failure.value


def install(svc):
    prior = (app.state.designs, app.state.alignment_reviews)
    app.state.designs, app.state.alignment_reviews = svc.designs, svc
    return prior


def restore(prior):
    app.state.designs, app.state.alignment_reviews = prior


def wrong_behavior_package():
    """Structurally valid, semantically wrong: the confirmed gap is about explaining the
    resolution, the package trains documentation. Every reference still checks out."""
    raw = package()
    raw["target_behaviors"][0]["description"] = "Accurately documents every interaction field after the call."
    raw["objectives"][0] |= {"observable_action": "complete every documentation field",
                             "standard": "all interaction fields are filled correctly",
                             "measurable_outcome": "After a simulated call, the learner completes every documentation field correctly."}
    raw["activities"][0] |= {"activity_type": "worksheet", "purpose": "Practice the documentation worksheet.",
                             "instructions": "The learner fills in the documentation worksheet for a sample call."}
    return raw


# --- A: fully aligned package -> design_aligned -----------------------------------------------

def test_case_a_fully_aligned_package_becomes_design_aligned():
    svc, validator, service, result, interventions = reviewed()
    record = interventions.get("hyp_1")
    stored = review(svc)
    assert stored.design_status == "design_aligned" and stored.overall_outcome == "aligned"
    assert all(getattr(stored.dimensions, name).outcome == "aligned" for name in DIMENSIONS)
    assert stored.misaligned_element_ids == () and stored.unsupported_assumptions == ()
    assert stored.run_id == result.run_id and stored.diagnosis_id == "hyp_1"
    assert stored.intervention_id == record.proposal.intervention_id
    assert stored.solution_validation_id == record.solution_validation.solution_validation_id
    assert stored.design_digest == design_digest(result.training_design)
    assert stored.assessed == "training_design_package" and stored.structural_trace == "structural_references_only"
    assert stored.alignment_review_id.startswith("alr_") and stored.provider_reported_confidence == 0.8
    assert stored.provider_metadata.provider == "controlled fixture"
    assert stored.provider_metadata.generation_mode == "controlled_fixture"
    assert len(validator.requests) == 1
    assert design_status_for("aligned") == "design_aligned"
    for outcome in ("partially_aligned", "misaligned", "insufficient_information"):
        assert design_status_for(outcome) == "design_questioned"


def test_case_a_bedrock_adapter_stamps_provenance_locally():
    svc, validator, service, _, _ = reviewed(bedrock=True)
    stored = review(svc)
    call = validator._client.calls[0]
    assert set(call) == {"modelId", "system", "messages", "inferenceConfig"}
    assert call["modelId"] == "global.anthropic.claude-sonnet-4-6" and validator.region == "us-east-1"
    assert call["system"] == [{"text": SYSTEM_PROMPT}] and call["inferenceConfig"]["temperature"] == 0
    meta = stored.provider_metadata
    assert (meta.provider, meta.model, meta.invocation_region, meta.generation_mode) == (
        "Amazon Bedrock", validator.model_id, validator.region, "provider")
    assert alignment_provider_kind(validator) == "provider"
    assert alignment_provider_kind(ControlledAlignmentValidator({})) == "controlled_fixture"
    assert alignment_provider_kind(UnavailableAlignmentValidator()) == "unavailable"


# --- B: structurally valid but wrong target behavior -> questioned --------------------------------

def test_case_b_wrong_target_behavior_is_questioned_even_though_references_are_valid():
    svc, validator, service, result, _ = reviewed(questioned("gap_to_target_behavior", ["B1"]),
                                                  package_text=wrong_behavior_package())
    assert result.alignment_trace.assessment == "structural_references_only"  # AWS-5 was satisfied.
    stored = review(svc)
    assert stored.design_status == "design_questioned" and stored.overall_outcome == "misaligned"
    assert stored.dimensions.gap_to_target_behavior.outcome == "misaligned"
    assert stored.dimensions.gap_to_target_behavior.misaligned_element_ids == (result.run_id + "/B1",)
    assert stored.misaligned_element_ids == (result.run_id + "/B1",)
    # The reviewer received the semantic content it needs to make that call.
    request = validator.requests[0]
    assert request["confirmed_performance_gap"]["observed_behavior"] == result.approved_diagnosis.diagnosis.observed_behavioral_defect
    assert request["training_package"]["target_behaviors"] == [
        {"id": "B1", "description": "Accurately documents every interaction field after the call."}]
    assert request["validated_intervention"]["target_change"] == result.intervention.target_change


# --- C/D/E/F: each downstream link can be questioned on its own -----------------------------------

@pytest.mark.parametrize("name,labels,suffixes", [
    ("target_behavior_to_objective", ["O1"], ["/O1"]),                     # C: unrelated objective
    ("objective_to_activity", ["A1"], ["/A1"]),                            # D: unrelated activity
    ("target_behavior_to_practice", ["P1", "BEAT1"], ["/P1", "/BEAT1"]),   # E: practice does not exercise it
    ("practice_to_rubric", ["R1"], ["/R1"]),                               # F: rubric scores the wrong behavior
    ("objective_to_knowledge_check", ["K1"], ["/K1"]),                     # knowledge check assesses recall
    ("intervention_to_package", ["A2", "O1"], ["/A2", "/O1"]),             # package drifts from the intervention
])
def test_case_cdef_questioned_links_resolve_to_stored_elements(name, labels, suffixes):
    svc, _, _, result, _ = reviewed(questioned(name, labels))
    stored = review(svc)
    assert stored.design_status == "design_questioned" and stored.overall_outcome == "misaligned"
    assert getattr(stored.dimensions, name).misaligned_element_ids == tuple(result.run_id + s for s in suffixes)
    assert stored.misaligned_element_ids == tuple(result.run_id + s for s in suffixes)
    for other in DIMENSIONS:
        if other != name:
            assert getattr(stored.dimensions, other).outcome == "aligned"


def test_partially_aligned_dimension_yields_a_questioned_partial_review():
    svc, _, _, _, _ = reviewed(alignment_response(
        "partially_aligned", objective_to_activity=dimension("partially_aligned", ["A1"])))
    stored = review(svc)
    assert stored.overall_outcome == "partially_aligned" and stored.design_status == "design_questioned"


# --- G: unsupported operational assumption -> questioned / flagged -------------------------------

def test_case_g_unsupported_assumption_questions_the_design_and_cannot_coexist_with_aligned():
    flagged = alignment_response("partially_aligned", unsupported=["Assumes a follow-up message is sent automatically."])
    svc, _, _, _, _ = reviewed(flagged)
    stored = review(svc)
    assert stored.design_status == "design_questioned"
    assert stored.unsupported_assumptions == ("Assumes a follow-up message is sent automatically.",)
    # An "aligned" verdict that names an unsupported assumption is incoherent and refused.
    svc, _, _, _, _ = reviewed(alignment_response("aligned", unsupported=["Assumes an automatic message."]))
    refused(svc)


# --- H: missing information -> insufficient_information / questioned -----------------------------

def test_case_h_missing_information_is_insufficient_information_and_questioned():
    svc, _, _, _, _ = reviewed(alignment_response("insufficient_information", missing=["The resolution options agents may offer."]))
    stored = review(svc)
    assert stored.design_status == "design_questioned" and stored.overall_outcome == "insufficient_information"
    assert stored.missing_information == ("The resolution options agents may offer.",)
    svc, _, _, _, _ = reviewed(alignment_response("insufficient_information"))
    refused(svc)  # Insufficient without naming what is missing.
    svc, _, _, _, _ = reviewed(alignment_response("aligned", gap_to_target_behavior=dimension("insufficient_information")))
    refused(svc)  # A dimension that could not be judged cannot roll up to aligned.


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(overall_outcome="aligned", dimensions=r["dimensions"] | {"objective_to_activity": dimension("misaligned", ["A1"])}),
    lambda r: r.update(overall_outcome="misaligned"),                      # nothing misaligned
    lambda r: r.update(overall_outcome="partially_aligned"),               # nothing questioned at all
    lambda r: r.update(overall_outcome="partially_aligned", dimensions={n: dimension("misaligned", ["B1"] if n == "gap_to_target_behavior" else []) for n in DIMENSIONS}),
    lambda r: r.update(missing_information=["Missing policy detail."]),
    lambda r: r.update(overall_outcome="partially_aligned", missing_information=["Missing policy detail."]),
    lambda r: r.update(overall_outcome="partially_aligned", dimensions=r["dimensions"] | {"objective_to_activity": dimension("misaligned", ["A1"])}),
    lambda r: r.update(overall_outcome="partially_aligned", dimensions=r["dimensions"] | {"objective_to_activity": dimension("insufficient_information")}),
    lambda r: r.update(overall_outcome="insufficient_information", missing_information=["Missing policy detail."], dimensions=r["dimensions"] | {"objective_to_activity": dimension("misaligned", ["A1"])}),
    lambda r: r["dimensions"]["gap_to_target_behavior"].update(outcome="aligned", misaligned_element_ids=["B1"]),
    lambda r: r["dimensions"]["objective_to_knowledge_check"].update(outcome="not_applicable"),  # the package has a check
    lambda r: r["dimensions"]["practice_to_rubric"].update(outcome="not_applicable"),
])
def test_incoherent_outcomes_are_refused_not_repaired(mutate):
    raw = alignment_response()
    mutate(raw)
    svc, _, _, _, _ = reviewed(raw)
    refused(svc)


def test_knowledge_check_dimension_is_not_applicable_exactly_when_the_package_has_no_check():
    svc, _, service, result, _ = reviewed()
    without_checks = result.model_copy(update={"training_design": result.training_design.model_copy(
        update={"decision_checks": ()})}, deep=True)
    view = build_alignment_view(without_checks, "criterion")
    assert view.has_knowledge_checks is False and view.request["training_package"]["knowledge_checks"] == []
    parsed = parse_alignment_response(json.dumps(alignment_response(objective_to_knowledge_check=dimension("not_applicable"))), view)
    assert parsed.dimensions.objective_to_knowledge_check.outcome == "not_applicable"
    with pytest.raises(AlignmentOutputError):
        parse_alignment_response(json.dumps(alignment_response()), view)  # aligned verdict on a check that does not exist
    with pytest.raises(AlignmentOutputError):
        parse_alignment_response(json.dumps(alignment_response(objective_to_knowledge_check=dimension("not_applicable", ["O1"]))), view)


# --- I: fabricated, cross-run, or impossible design element IDs fail closed ---------------------

@pytest.mark.parametrize("name,ids", [
    ("gap_to_target_behavior", ["B9"]),                       # fabricated
    ("gap_to_target_behavior", ["design_other/B1"]),          # cross-run
    ("objective_to_activity", ["O1", "A9"]),                  # one valid, one fabricated
    ("gap_to_target_behavior", ["R1"]),                       # impossible: a rubric criterion under the gap link
    ("practice_to_rubric", ["B1"]),                           # impossible: a behavior under the rubric link
    ("objective_to_knowledge_check", ["K1_OPT1"]),            # options are not reviewable elements
    ("target_behavior_to_practice", ["PERSONA1"]),            # neither are personas
    ("intervention_to_package", ["S1"]),                      # nor outline sections
    ("intervention_to_package", ["GAP-001"]),                 # nor the upstream references
])
def test_case_i_unknown_cross_run_or_impossible_references_fail_closed(name, ids):
    svc, validator, _, _, _ = reviewed(questioned(name, ids))
    refused(svc)
    assert len(validator.requests) == 1


def test_case_i_run_prefixed_identifiers_are_not_accepted_as_labels():
    svc, _, _, result, _ = reviewed()
    view = build_alignment_view(result, "criterion")
    assert set(view.elements) == {"B1", "O1", "A1", "A2", "K1", "P1", "BEAT1", "BEAT2", "R1"}
    assert view.elements["BEAT1"] == ("practice_turn", result.run_id + "/BEAT1")
    with pytest.raises(AlignmentOutputError):
        parse_alignment_response(json.dumps(questioned("gap_to_target_behavior", [result.run_id + "/B1"])), view)


# --- J: duplicate IDs and duplicate JSON keys fail closed -----------------------------------------

def test_case_j_duplicate_element_ids_and_duplicate_json_keys_fail_closed():
    svc, _, _, _, _ = reviewed(questioned("target_behavior_to_practice", ["P1", "P1"]))
    refused(svc)
    duplicate = json.dumps(alignment_response())[:-1] + ',"overall_outcome":"misaligned"}'
    svc, _, _, _, _ = reviewed(validator=ControlledAlignmentValidator(duplicate))
    refused(svc)


# --- K: malformed JSON fails closed -------------------------------------------------------------

@pytest.mark.parametrize("text,stop", [
    ("not json", "end_turn"),
    ("```json\n" + json.dumps(alignment_response()) + "\n```", "end_turn"),
    (json.dumps([alignment_response()]), "end_turn"),
    ("", "end_turn"),
    (json.dumps(alignment_response()), "max_tokens"),
    (json.dumps(alignment_response()), "guardrail_intervened"),
])
def test_case_k_malformed_or_incomplete_bedrock_output_is_refused_and_not_stored(text, stop):
    runtime = FakeRuntime(text, stop_reason=stop)
    svc, _, service, _, _ = reviewed(validator=None, bedrock=False)
    svc.validator = BedrockAlignmentValidator(client=runtime, diagnostics=service.diagnostics)
    refused(svc)
    assert len(runtime.calls) == 1
    runtime.text, runtime.stop_reason = json.dumps(alignment_response()), "end_turn"
    assert review(svc).design_status == "design_aligned"  # A failed call stores nothing and may be retried.


def test_converse_text_accepts_reasoning_blocks_but_not_tool_use():
    ok = {"stopReason": "end_turn", "output": {"message": {"content": [
        {"reasoningContent": {"reasoningText": {"text": "thinking"}}}, {"text": "{}"}]}}}
    assert converse_text(ok) == "{}"
    for bad in ({"stopReason": "end_turn", "output": {"message": {"content": [{"toolUse": {}}]}}},
                {"stopReason": "end_turn", "output": {"message": {"content": "{}"}}}, "text", None):
        with pytest.raises(AlignmentOutputError):
            converse_text(bad)


# --- L: extra keys and primitive coercion fail closed ---------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda r: r.update(extra_key="x"),
    lambda r: r.update(status="design_aligned"),
    lambda r: r.update(design_status="design_aligned"),
    lambda r: r.update(provider="trusted", model="m", invocation_region="us-east-1"),
    lambda r: r.update(run_id="design_forged", diagnosis_id="hyp_other"),
    lambda r: r["dimensions"].update(eighth_dimension=dimension()),
    lambda r: r["dimensions"].pop("practice_to_rubric"),
    lambda r: r["dimensions"]["gap_to_target_behavior"].update(suggested_behavior="Explain resolution options."),
    lambda r: r.pop("unsupported_assumptions"),
    lambda r: r.pop("dimensions"),
    lambda r: r.update(provider_reported_confidence="0.8"),
    lambda r: r.update(provider_reported_confidence="high"),
    lambda r: r.update(provider_reported_confidence=True),
    lambda r: r.update(provider_reported_confidence=1.5),
    lambda r: r.update(overall_outcome=1),
    lambda r: r.update(overall_outcome="supported"),
    lambda r: r.update(overall_assessment="   "),
    lambda r: r.update(missing_information="none"),
    lambda r: r.update(unsupported_assumptions=[""]),
    lambda r: r["dimensions"]["objective_to_activity"].update(misaligned_element_ids="A1"),
    lambda r: r["dimensions"]["objective_to_activity"].update(outcome=None),
])
def test_case_l_extra_keys_and_coercion_fail_closed(mutate):
    raw = alignment_response()
    mutate(raw)
    svc, _, _, _, _ = reviewed(raw)
    refused(svc)


# --- M: the provider cannot change the diagnosis, the intervention, or the design ---------------

@pytest.mark.parametrize("forged", [
    {"training_design": {"objectives": []}},
    {"revised_objectives": ["Document interaction fields correctly."]},
    {"replacement_activities": [{"id": "A3"}]},
    {"cause_domain": "process_gap"},
    {"intervention_type": "coaching"},
    {"validated_diagnosis": {"observed_behavioral_defect": "different"}},
])
def test_case_m_provider_output_that_carries_design_or_diagnosis_content_is_refused(forged):
    svc, _, _, _, _ = reviewed(alignment_response() | forged)
    refused(svc)


def test_case_m_review_leaves_every_upstream_record_untouched():
    svc, _, service, before, interventions = reviewed(questioned("objective_to_activity", ["A1"]))
    record_before = interventions.get("hyp_1")
    approved_before = service.diagnostics.get_approved_diagnosis("hyp_1")
    stored = review(svc)
    after = service.get("hyp_1")
    assert after == before and after.status == "ready_for_alignment_review"
    assert design_digest(after.training_design) == stored.design_digest
    assert after.alignment_trace == before.alignment_trace
    assert interventions.get("hyp_1") == record_before
    assert service.diagnostics.get_approved_diagnosis("hyp_1") == approved_before
    # The review record carries verdicts and identifiers only, never a copy of design content.
    assert set(AlignmentReview.model_fields) == {
        "alignment_review_id", "run_id", "diagnosis_id", "intervention_id", "solution_validation_id",
        "design_digest", "assessed", "structural_trace", "overall_outcome", "design_status", "overall_assessment",
        "dimensions", "misaligned_element_ids", "unsupported_assumptions", "missing_information",
        "provider_reported_confidence", "provider_metadata", "created_at"}
    serialized = json.dumps(stored.model_dump(mode="json"))
    assert before.training_design.objectives[0].measurable_outcome not in serialized
    assert "practice_scenarios" not in serialized and "target_behaviors" not in serialized
    with pytest.raises(ValidationError):
        AlignmentReview.model_validate(stored.model_dump(mode="json") | {"design_status": "design_aligned"} | {"overall_outcome": "aligned", "training_design": {}})
    with pytest.raises(ValidationError):  # Stored records are immutable.
        AlignmentReview.model_validate(stored.model_dump(mode="json") | {"assessed": "diagnosis"})


def test_case_m_stored_review_cannot_be_read_against_a_different_package():
    svc, _, service, result, _ = reviewed()
    review(svc)
    changed = result.training_design.model_copy(update={"performance_context": "Edited after review."})
    service._results["hyp_1"] = result.model_copy(update={"training_design": changed})
    with pytest.raises(DesignError) as failure:
        svc.get("hyp_1")
    assert failure.value.code == "alignment_review_stale"
    with pytest.raises(DesignError) as failure:
        review(svc)
    assert failure.value.code == "alignment_review_stale"


# --- N: idempotent repeated validation -----------------------------------------------------------

def test_case_n_repeated_review_returns_the_stored_record_without_another_call():
    svc, validator, _, _, _ = reviewed()
    first = review(svc)
    assert review(svc) == first and svc.get("hyp_1") == first and len(validator.requests) == 1
    assert svc.get("hyp_1") is not first  # Snapshots, never the stored object.
    prior = install(svc)
    try:
        with TestClient(app) as client:
            responses = [client.post("/designs/diagnoses/hyp_1/alignment-review") for _ in range(2)]
            assert [r.status_code for r in responses] == [200, 200]
            assert responses[0].json() == responses[1].json() == client.get("/designs/diagnoses/hyp_1/alignment-review").json()
            assert responses[0].json()["alignment_review_id"] == first.alignment_review_id
            assert responses[0].json()["design_status"] == "design_aligned"
    finally:
        restore(prior)
    assert len(validator.requests) == 1


# --- O: a failed provider call stores nothing --------------------------------------------------

def test_case_o_failed_provider_calls_store_nothing_and_are_sanitized():
    class Failing:
        async def review(self, request):
            raise RuntimeError("secret endpoint detail")

    svc, _, _, _, _ = reviewed(validator=Failing())
    failure = refused(svc, "alignment_validator_failure")
    assert "secret" not in str(failure)
    prior = install(svc)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1/alignment-review")
            assert failed.status_code == 502 and "secret" not in failed.text
            assert failed.json()["detail"] == {"code": "alignment_validator_failure",
                                               "message": ERROR_MESSAGES["alignment_validator_failure"]}
            assert client.get("/designs/diagnoses/hyp_1/alignment-review").status_code == 404
    finally:
        restore(prior)
    svc.validator = FakeAdapterFailure()
    refused(svc, "alignment_validator_failure")
    svc.validator = ControlledAlignmentValidator(alignment_response())
    assert review(svc).design_status == "design_aligned"


class FakeAdapterFailure:
    async def review(self, request):
        raise AlignmentReviewError("alignment_validator_failure")


def test_case_o_unavailable_validator_is_a_503_and_stores_nothing():
    svc, _, _, _, _ = reviewed(validator=UnavailableAlignmentValidator())
    refused(svc, "alignment_validator_unavailable")
    prior = install(svc)
    try:
        with TestClient(app) as client:
            assert client.post("/designs/diagnoses/hyp_1/alignment-review").status_code == 503
            assert client.get("/designs/diagnoses/hyp_1/alignment-review").status_code == 404
    finally:
        restore(prior)


def test_bedrock_client_failure_is_reported_as_a_generic_failure():
    runtime = FakeRuntime(error=RuntimeError("secret endpoint detail"))
    svc, _, service, _, _ = reviewed()
    svc.validator = BedrockAlignmentValidator(client=runtime, diagnostics=service.diagnostics)
    failure = refused(svc, "alignment_validator_failure")
    assert "secret" not in str(failure)


# --- P: the AWS-2 privacy boundary remains intact -----------------------------------------------

def test_case_p_request_is_an_allowlisted_semantic_view_without_rows_names_ids_or_counts():
    svc, validator, service, result, interventions = reviewed(bedrock=True)
    record = interventions.get("hyp_1")
    context = service._context("hyp_1")
    review(svc)
    call = validator._client.calls[0]
    request = json.loads(call["messages"][0]["content"][0]["text"])
    assert set(request) == REQUEST_KEYS and set(request["confirmed_performance_gap"]) == GAP_KEYS
    assert set(request["validated_intervention"]) == INTERVENTION_KEYS
    assert set(request["training_package"]) == PACKAGE_KEYS
    assert request["confirmed_performance_gap"]["qa_criterion"] == context.signal_criterion
    assert request["validated_intervention"]["recommendation"] == record.proposal.recommendation
    package_wire = request["training_package"]
    assert package_wire["target_behaviors"][0]["id"] == "B1" and package_wire["practice_scenarios"][0]["rubric"][0]["id"] == "R1"
    assert set(package_wire["knowledge_checks"][0]["options"][0]) == {"response", "feedback", "correct"}
    assert "name" not in package_wire["practice_scenarios"][0]["persona"]
    serialized = json.dumps(call)
    for leak in ("Person One", "Reviewer One", "Lead One", "lead", "eval_1", "eval_2", "ev_", "sig_", "synthetic.xlsx",
                 "Sheet", "missed greeting", "excel_row", "evaluator_feedback", "source_lineage", "item_id",
                 "evaluation_id", "hyp_1", "hypothesis_id", result.run_id, "design_", context.approved.signal_id,
                 "fail_count", "evaluated_results", "approved_by", "[reviewer]",
                 record.proposal.intervention_id, record.solution_validation.solution_validation_id,
                 "intervention_id", "solution_validation_id", "training_design_gate", "solution_alignment",
                 "permitted", "EVID-", "SIGNAL-", "duration_minutes", "outline", "section_id", "Morgan",
                 "generation_mode", "provider_metadata", "structural_references_only", "alignment_trace",
                 "guidance_version", "design_basis", "diagnosis_id"):
        assert leak not in serialized, leak
    # Identifiers on the wire are the bare package labels, never the run-prefixed stored IDs.
    body = json.dumps(request)
    assert '"B1"' in body and f'"{result.run_id}/B1"' not in body and result.run_id not in serialized
    # No count, rate, score, or duration field travels in the request body.
    assert not any(token in body for token in ("_count", "_rate", "_score", "duration_minutes", "evaluated_"))


@pytest.mark.parametrize("planted", ["Person One", "eval_2", "synthetic.xlsx", "Sheet1", "Person One missed greeting"])
def test_case_p_known_identifiers_in_the_generated_package_block_the_remote_call(planted):
    """AWS-5 output is stored unscreened; AWS-6 must not carry a leaked identifier further."""
    raw = package()
    raw["activities"][0]["instructions"] = f"The facilitator references {planted} while modelling the close."
    svc, validator, _, _, _ = reviewed(package_text=raw, bedrock=True)
    refused(svc, "alignment_privacy_blocked")
    assert validator._client.calls == []


def test_case_p_validator_without_a_bound_diagnostic_service_or_with_blocked_policy_sends_nothing():
    runtime = FakeRuntime(json.dumps(alignment_response()))
    svc, _, service, _, _ = reviewed()
    svc.validator = BedrockAlignmentValidator(client=runtime, diagnostics=None)
    refused(svc, "alignment_privacy_blocked")
    source, _, _ = prepared()
    svc.validator = BedrockAlignmentValidator(client=runtime, diagnostics=DiagnosticService(source, BedrockReasoner()))
    refused(svc, "alignment_privacy_blocked")
    assert runtime.calls == []
    prior = install(svc)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1/alignment-review")
            assert failed.status_code == 502
            assert failed.json()["detail"] == {"code": "alignment_privacy_blocked",
                                               "message": ERROR_MESSAGES["alignment_privacy_blocked"]}
    finally:
        restore(prior)


def test_system_prompt_carries_the_contract_and_no_evidence_vocabulary():
    contract = response_contract()
    assert contract in SYSTEM_PROMPT
    for key in AlignmentResponse.model_fields:
        assert f'"{key}"' in contract
    for name in DIMENSIONS:
        assert f'"{name}"' in contract and name in SYSTEM_PROMPT
    assert '"not_applicable"' in contract and "JSON number from 0 to 1 inclusive" in contract
    for phrase in ("Never rediagnose", "never rewrite", "was effective", "structural check"):
        assert phrase in SYSTEM_PROMPT
    for leak in ("EVID-", "evaluator_feedback", "excel_row", "SIGNAL-001", "fail_count"):
        assert leak not in SYSTEM_PROMPT


# --- Q: the AWS-5 structural trace stays structural ---------------------------------------------

def test_case_q_structural_trace_remains_structural_references_only_and_the_design_never_claims_alignment():
    svc, _, service, result, _ = reviewed()
    stored = review(svc)
    after = service.get("hyp_1")
    assert after.alignment_trace.assessment == "structural_references_only"
    assert after.alignment_trace == result.alignment_trace and after.status == "ready_for_alignment_review"
    design_only = json.dumps({"training_design": after.training_design.model_dump(mode="json"),
                              "alignment_trace": after.alignment_trace.model_dump(mode="json")}).lower()
    assert "design_aligned" not in design_only and "aligned" not in design_only.replace('"solution_alignment": "aligned"', "")
    assert stored.structural_trace == "structural_references_only" and stored.design_status == "design_aligned"
    review_text = json.dumps(stored.model_dump(mode="json")).lower()
    for claim in ("validated training", "approved training", "deployed", "outcome validated", "improved", "effective"):
        assert claim not in review_text


# --- Gating: what may be reviewed --------------------------------------------------------------

def test_review_requires_a_stored_training_package_from_the_aws4_handoff():
    # No design run at all.
    svc, validator, service, _, _ = reviewed()
    empty = AlignmentReviewService(setup()[0], ControlledAlignmentValidator(alignment_response()))
    with pytest.raises(DesignError) as failure:
        review(empty)
    assert failure.value.code == "design_not_found"
    # A non-training design has nothing to align.
    runtime = FakeRuntime()
    process, _, _, _ = setup(intervention_type="process_correction", runtime=runtime)
    assert run(process).training_design is None and runtime.calls == []
    svc = AlignmentReviewService(process, ControlledAlignmentValidator(alignment_response()))
    refused(svc, "no_training_design")
    # The controlled M5 fixture decision carries no validated intervention to align against.
    fixture_service, _ = _fixture_service()
    assert run(fixture_service).training_design is not None
    svc = AlignmentReviewService(fixture_service, ControlledAlignmentValidator(alignment_response()))
    refused(svc, "alignment_review_not_permitted")
    assert svc.validator.requests == []
    # A fixture-shaped result cannot reuse valid AWS-4 fields to look integrated.
    provider_svc, provider_validator, provider_designs, integrated, _ = reviewed()
    provider_designs._results["hyp_1"] = integrated.model_copy(update={"generation_mode": "controlled_fixture"})
    refused(provider_svc, "alignment_review_not_permitted")
    assert provider_validator.requests == []
    prior = install(svc)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1/alignment-review")
            assert failed.status_code == 409 and failed.json()["detail"]["code"] == "alignment_review_not_permitted"
            assert client.get("/designs/diagnoses/hyp_1/alignment-review").status_code == 404
            assert client.get("/designs/diagnoses/hyp_9/alignment-review").status_code == 404
    finally:
        restore(prior)


def test_api_reads_and_writes_follow_the_design_router_conventions():
    svc, _, _, result, _ = reviewed(questioned("practice_to_rubric", ["R1"]))
    prior = install(svc)
    try:
        with TestClient(app) as client:
            missing = client.get("/designs/diagnoses/hyp_1/alignment-review")
            assert missing.status_code == 404 and missing.json()["detail"]["code"] == "alignment_review_not_found"
            created = client.post("/designs/diagnoses/hyp_1/alignment-review")
            assert created.status_code == 200
            body = created.json()
            assert body["design_status"] == "design_questioned" and body["overall_outcome"] == "misaligned"
            assert body["misaligned_element_ids"] == [result.run_id + "/R1"]
            assert body["structural_trace"] == "structural_references_only"
            assert body["provider_metadata"]["generation_mode"] == "controlled_fixture"
            assert client.get("/designs/diagnoses/hyp_1").json()["status"] == "ready_for_alignment_review"
            assert client.get("/diagnostics/mode").json()["alignment_validator"] == "controlled_fixture"
    finally:
        restore(prior)


def test_default_startup_installs_no_alignment_validator_and_bedrock_startup_binds_one():
    source, signal, bundle = prepared()
    from app.diagnostics.engine import ControlledTestReasoner
    from test_diagnostics import response
    diagnosis = DiagnosticService(source, ControlledTestReasoner(response(bundle)))
    built = build_pipeline(diagnosis, Settings(bedrock_enabled=True, _env_file=None))
    assert isinstance(built.alignment_reviews.validator, BedrockAlignmentValidator)
    assert built.alignment_reviews.designs is built.designs
    assert built.alignment_reviews.validator._diagnostics is diagnosis

    class State:
        pass

    class Holder:
        state = State()

    holder = Holder()
    installed = install_pipeline(holder, diagnosis, Settings(_env_file=None))
    assert holder.state.alignment_reviews is installed.alignment_reviews
    # Fresh processes, so no other test's re-installation of the shared app can interfere.
    script = """
import json
from fastapi.testclient import TestClient
from app.main import app
reviews = app.state.alignment_reviews
print(json.dumps({"validator": type(reviews.validator).__name__,
                  "same_designs": reviews.designs is app.state.designs,
                  "same_diagnostics": getattr(reviews.validator, "_diagnostics", None) is app.state.diagnostics,
                  "mode": TestClient(app).get("/diagnostics/mode").json()["alignment_validator"]}))
"""
    repo = Path(__file__).resolve().parents[3]
    for enabled, expected in (("false", {"validator": "UnavailableAlignmentValidator", "same_designs": True,
                                         "same_diagnostics": False, "mode": "unavailable"}),
                              ("true", {"validator": "BedrockAlignmentValidator", "same_designs": True,
                                        "same_diagnostics": True, "mode": "provider"})):
        env = {k: v for k, v in os.environ.items() if not k.startswith("COACHLENS_")}
        env |= {"PYTHONPATH": str(repo / "services" / "api"), "COACHLENS_BEDROCK_ENABLED": enabled}
        run_ = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60)
        assert run_.returncode == 0, run_.stderr
        assert json.loads(run_.stdout.strip().splitlines()[-1]) == expected


def test_review_view_is_pure_and_the_parser_resolves_labels_to_stored_ids():
    svc, _, _, result, _ = reviewed()
    view = build_alignment_view(result, "criterion")
    assert view.design_digest == design_digest(result.training_design)
    parsed = parse_alignment_response(json.dumps(questioned("objective_to_activity", ["A1", "O1"])), view)
    assert parsed.dimensions.objective_to_activity.misaligned_element_ids == ["A1", "O1"]
    stored = review(AlignmentReviewService(svc.designs, ControlledAlignmentValidator(
        questioned("objective_to_activity", ["A1", "O1"]))))
    assert stored.dimensions.objective_to_activity.misaligned_element_ids == (result.run_id + "/A1", result.run_id + "/O1")
    assert deepcopy(view.request) == view.request
