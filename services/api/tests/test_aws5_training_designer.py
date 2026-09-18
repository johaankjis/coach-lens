"""AWS-5 Training Designer tests. Synthetic QA rows, a fake Converse runtime, no AWS.

Case labels (A-N) follow the AWS-5 milestone test list. Since the AWS-4/AWS-5 integration
every provider-backed design run here goes through the real chain: human-approved diagnosis
-> AWS-4 Intervention Reasoner (controlled fixture) -> AWS-4 Solution Validator (controlled
fixture) -> `ValidatedInterventionHandoff` -> `BedrockTrainingDesigner` with a fake runtime.
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

from app.design.alignment import build_alignment_trace
from app.design.bedrock import (GAP_REFERENCE, INTERVENTION_KEYS, REQUEST_KEYS, SYSTEM_PROMPT,
                                BedrockTrainingDesigner, DesignerResponse, build_designer_request,
                                converse_text, parse_designer_response, response_contract,
                                to_training_design)
from app.design.demo import DemoDesignFixture
from app.design.guidance import DESIGN_CHAIN, GUIDANCE_VERSION, PRINCIPLES, guidance_text
from app.design.intervention_input import (ValidatedTrainingIntervention,
                                           training_focus_for, training_intervention_from_decision)
from app.design.models import (AWS4_VALIDATION_SOURCE, DesignResult, InterventionDecision,
                               TrainingDesign, TrainingFocus)
from app.design.service import (PASSTHROUGH_DESIGN_ERRORS, REFUSAL_MESSAGES, DesignError, DesignService,
                                TrainingDesignRefused, UnavailableDesignProvider, design_provider_kind)
from app.design.validation import InvalidDesignOutput, validate_decision, validate_training
from app.diagnostics.bedrock import BedrockReasoner
from app.diagnostics.engine import ControlledTestReasoner, DiagnosticService
from app.interventions.handoff import ValidatedInterventionHandoff, decision_from_record
from app.interventions.service import (ControlledInterventionReasoner, ControlledSolutionValidator,
                                       InterventionService)
from app.main import app
from test_aws4_interventions import intervention_response, solution_response
from test_diagnostics import prepared, response, revision


# --- Fixtures ---------------------------------------------------------------------------

def knowledge_check():
    return {"id": "K1", "objective_ids": ["O1"], "behavior_ids": ["B1"],
            "situation": "A member asks what happens now that the request is updated.",
            "question": "Which response completes the closing sequence?",
            "options": [
                {"id": "K1_OPT1", "response": "The request is updated. Thanks for calling.",
                 "feedback": "This omits the next action and does not check the member's understanding.", "correct": False},
                {"id": "K1_OPT2", "response": "Your request is updated; you will get a message about the next step. What do you expect to happen next?",
                 "feedback": "This states the resolution, names the next action, and checks understanding.", "correct": True},
                {"id": "K1_OPT3", "response": "You can call back if you have questions.",
                 "feedback": "This defers the next action to the member instead of naming it.", "correct": False},
                {"id": "K1_OPT4", "response": "The team will take care of it from here.",
                 "feedback": "This is too vague for the member to know the next step.", "correct": False}]}


def beat(number, trigger, likely, expected):
    return {"id": f"BEAT{number}", "trigger": trigger, "likely_response": likely,
            "expected_learner_behavior": expected,
            "success_branch": "The persona acknowledges the step and asks about timing.",
            "challenge_branch": "The persona repeats the question and sounds more frustrated.",
            "facilitator_cue": "Listen for the resolution, the next action, and a confirming question.",
            "behavior_ids": ["B1"]}


def package(focus="skill", **changes):
    """A valid designer response for a one-behavior closing-sequence package."""
    raw = {
        "performance_context": "The learner closes calls without a clear resolution summary. This package trains a complete closing sequence.",
        "target_behaviors": [{"id": "B1", "gap_reference": GAP_REFERENCE,
                              "description": "States the resolution and the next action, then asks the member to confirm the next step before closing."}],
        "objectives": [{"id": "O1", "behavior_ids": ["B1"],
                        "condition": "During a simulated member call about an updated request",
                        "observable_action": "state the resolution, name the next action, and ask a confirming question",
                        "standard": "all three elements are audible before the close in every simulated call",
                        "measurable_outcome": "During a simulated member call, the learner states the resolution, names the next action, and asks a confirming question before closing."}],
        "outline": [{"id": "S1", "title": "Model the closing sequence", "purpose": "Show the target behavior.",
                     "duration_minutes": 10, "objective_ids": ["O1"], "activity_ids": ["A1"]},
                    {"id": "S2", "title": "Rehearse with a member persona", "purpose": "Apply the behavior under challenge.",
                     "duration_minutes": 15, "objective_ids": ["O1"], "activity_ids": ["A2"]}],
        "activities": [{"id": "A1", "activity_type": "demonstration", "purpose": "Show a complete closing sequence.",
                        "instructions": "The facilitator closes a sample call, then the learner names the three elements heard.",
                        "objective_ids": ["O1"], "expected_learner_behavior": "Names resolution, next action, and confirming question.",
                        "success_indicator": "All three elements named without prompting.", "duration_minutes": 10},
                       {"id": "A2", "activity_type": "simulation", "purpose": "Practice the closing sequence with a member persona.",
                        "instructions": "Run the practice scenario, then debrief with the rubric.",
                        "objective_ids": ["O1"], "expected_learner_behavior": "Delivers the closing sequence under challenge.",
                        "success_indicator": "Rubric criterion met.", "duration_minutes": 15}],
        "knowledge_checks": [knowledge_check()],
        "practice_scenarios": [{
            "id": "P1", "title": "Confirm a follow-up resolution",
            "call_driver": "The member wants to know what happens now that a request was updated.",
            "scenario_setup": "The facilitator plays the member. The learner has the request status in front of them.",
            "learner_role": "Member services representative",
            "persona": {"id": "PERSONA1", "name": "Morgan", "context": "Was told a request was updated but is unsure what happens next.",
                        "communication_style": "Direct, short follow-up questions.", "emotional_state": "Mildly frustrated",
                        "knows": "A request was submitted.", "wants": "A precise next step and timing.",
                        "withholding": "Does not volunteer that the earlier explanation was confusing.",
                        "success_response": "Restates the next step and agrees to close.",
                        "failure_response": "Asks again what happens next and resists closing."},
            "learner_objective": "Deliver and verify a complete resolution summary.",
            "opening_line": "I heard it was updated, but what exactly happens now?",
            "behavior_ids": ["B1"], "objective_ids": ["O1"], "activity_id": "A2",
            "beats": [beat(1, "The learner explains the update.", "So do I need to call again?",
                           "Name the specific next action and who takes it."),
                      beat(2, "The learner names the next action.", "And when will that happen?",
                           "State the timing if known, otherwise use the placeholder for timing, then ask a confirming question.")],
            "escalation_expectation": None,
            "completion_criteria": ["The learner states the resolution, the next action, and asks a confirming question before closing."],
            "rubric": [{"id": "R1", "behavior_id": "B1", "objective_id": "O1",
                        "practice_behavior": "Summarize the resolution and next action, then check understanding.",
                        "observable_success": "All three components occur before the close and the member answers the check.",
                        "scoring_guidance": "Met only when resolution, specific next action, and a confirming question are explicit."}],
            "debrief_prompts": ["Which phrase made the next action clear?", "What did the member say after your confirming question?"]}],
        "missing_operational_details": [],
    }
    return raw | changes


class FakeRuntime:
    def __init__(self, text=None, error=None, stop_reason="end_turn"):
        self.text = json.dumps(package()) if text is None else text
        self.error = error
        self.stop_reason = stop_reason
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": self.text}]}},
                "stopReason": self.stop_reason, "ResponseMetadata": {"RequestId": "synthetic-request-id"}}


def solution_for(alignment):
    """A grounded AWS-4 solution review for each outcome (see `SolutionResponse` rules)."""
    return {"aligned": solution_response(),
            "partially_aligned": solution_response(alignment_outcome="partially_aligned",
                                                   missing_information=["What the agents were taught"]),
            "misaligned": solution_response(alignment_outcome="misaligned", aligned_points=[],
                                            misaligned_points=["The type does not address the cause"]),
            "insufficient_evidence": solution_response(alignment_outcome="insufficient_evidence",
                                                       aligned_points=[],
                                                       missing_information=["Direct observation"])}[alignment]


def setup(cause="skill_gap", intervention_type="practice_simulation", alignment="aligned", *,
          runtime=None, revised_explanation=None, operational_context=(), diagnostics_for_designer="same",
          intervention_changes=None):
    """The integrated path with a fake Converse runtime for the designer only."""
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(
        response(bundle, cause_domain=cause, performance_dimension="capability")))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    if revised_explanation is not None:
        diagnosis.revise("hyp_1", "lead", revision(bundle, cause_domain=cause, explanation=revised_explanation),
                         "Reviewer revised the explanation")
    diagnosis.approve("hyp_1", "lead")
    changes = {"intervention_type": intervention_type} | (intervention_changes or {})
    if intervention_type == "investigate_further":
        changes.setdefault("missing_evidence", ["Evaluator observations of the closing sequence"])
    interventions = InterventionService(diagnosis, None, ControlledInterventionReasoner(intervention_response(**changes)),
                                        ControlledSolutionValidator(solution_for(alignment)))
    asyncio.run(interventions.propose("hyp_1"))
    asyncio.run(interventions.validate_solution("hyp_1"))
    runtime = runtime or FakeRuntime()
    bound = diagnosis if diagnostics_for_designer == "same" else diagnostics_for_designer
    designer = BedrockTrainingDesigner(client=runtime, diagnostics=bound,
                                       operational_context=operational_context)
    service = DesignService(diagnosis, ValidatedInterventionHandoff(interventions), designer)
    return service, runtime, designer, interventions


def handoff_decision(service, interventions):
    """The validated M5 decision exactly as the handoff would hand it to the designer."""
    context = service._context("hyp_1")
    return context, validate_decision(decision_from_record(interventions.get("hyp_1"), context), context)


def run(service):
    return asyncio.run(service.run("hyp_1"))


def refused(service, reason):
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "training_design_refused"
    assert str(failure.value) == REFUSAL_MESSAGES[reason]
    return failure.value


def with_client(service):
    prior = app.state.designs
    app.state.designs = service
    return prior


# --- A: knowledge intervention -> objective, activity, knowledge check, traceable ---------

def test_knowledge_intervention_produces_traceable_objective_activity_and_check():
    service, runtime, _, interventions = setup(cause="knowledge_gap", intervention_type="training",
                                               runtime=FakeRuntime(json.dumps(package("knowledge"))))
    result = run(service)
    design = result.training_design
    record = interventions.get("hyp_1")
    assert result.status == "ready_for_alignment_review" and result.generation_mode == "provider"
    assert design.design_basis.intervention.training_focus == TrainingFocus.KNOWLEDGE
    assert design.design_basis.intervention.validation_source == AWS4_VALIDATION_SOURCE
    assert design.design_basis.intervention.intervention_type == "training"
    assert design.design_basis.intervention.intervention_id == record.proposal.intervention_id
    assert design.design_basis.intervention.solution_validation_id == record.solution_validation.solution_validation_id
    assert design.design_basis.intervention.training_design_gate == "permitted"
    assert design.design_basis.gap.cause_domain == "knowledge_gap"
    assert design.design_basis.guidance_version == GUIDANCE_VERSION
    run_id = result.run_id
    check = design.decision_checks[0]
    objective = next(o for o in design.objectives if o.objective_id in check.objective_ids)
    assert check.behavior_ids == (run_id + "/B1",) and objective.behavior_ids == (run_id + "/B1",)
    assert design.target_behaviors[0].behavior_id == run_id + "/B1"
    assert design.target_behaviors[0].diagnosis_id == "hyp_1"
    activity = next(a for a in design.activities if objective.objective_id in a.objective_ids)
    assert any(activity.activity_id in section.activity_ids for section in design.outline)
    assert result.alignment_trace.knowledge_check_links[0].behavior_ids == (run_id + "/B1",)
    assert len(runtime.calls) == 1


def test_knowledge_focus_without_a_knowledge_check_is_refused():
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(package("skill") | {"knowledge_checks": []}), TrainingFocus.KNOWLEDGE)
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(package("skill") | {"knowledge_checks": []}), TrainingFocus.KNOWLEDGE_AND_SKILL)
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(package("skill") | {"knowledge_checks": []}), TrainingFocus.SKILL)


# --- B: skill intervention -> meaningful hands-on simulation ------------------------------

def test_skill_intervention_produces_scripted_practice():
    service, _, _, _ = setup(cause="skill_gap")
    result = run(service)
    design = result.training_design
    assert design.design_basis.intervention.training_focus == TrainingFocus.SKILL
    scenario = design.practice_scenarios[0]
    assert scenario.scenario_setup and scenario.persona.name == "Morgan" and scenario.opening_line
    assert len(scenario.beats) >= 2
    for turn in scenario.beats:
        assert turn.expected_learner_behavior and turn.facilitator_cue and turn.likely_response
        assert set(turn.behavior_ids) <= set(scenario.behavior_ids)
    assert scenario.escalation_expectation is None  # None was supplied, none invented.
    assert scenario.completion_criteria and scenario.debrief_prompts
    assert scenario.rubric[0].behavior_id == result.run_id + "/B1"


def test_skill_focus_requires_at_least_two_scripted_turns():
    thin = package()
    thin["practice_scenarios"][0]["beats"] = thin["practice_scenarios"][0]["beats"][:1]
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(thin), TrainingFocus.SKILL)
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(thin), TrainingFocus.KNOWLEDGE)


# --- C/D: non-training, process-only, investigate, undetermined are refused --------------

@pytest.mark.parametrize("intervention_type,alignment,reason", [
    ("coaching", "aligned", "not_training_intervention"),
    ("process_correction", "aligned", "not_training_intervention"),
    ("investigate_further", "aligned", "investigation_required"),
    ("training", "partially_aligned", "training_design_not_permitted"),
    ("practice_simulation", "misaligned", "training_design_not_permitted"),
    ("training", "insufficient_evidence", "training_design_not_permitted"),
])
def test_designer_refuses_non_designable_interventions_even_when_called_directly(intervention_type, alignment, reason):
    """The service never reaches the designer for these; a direct caller gets the same answer."""
    service, runtime, designer, interventions = setup(intervention_type=intervention_type, alignment=alignment)
    context, decision = handoff_decision(service, interventions)
    with pytest.raises(TrainingDesignRefused) as failure:
        asyncio.run(designer.design(context.provider_view(), decision))
    assert failure.value.reason == reason and runtime.calls == []
    with pytest.raises(TrainingDesignRefused):
        training_intervention_from_decision(context, decision)


def test_designer_refuses_a_decision_that_did_not_come_from_aws4():
    """The retired cause-derived route: a fixture decision carries no AWS-4 fields, so even a
    confirmed skill gap with a `training` decision is not designable by a provider."""
    service, runtime, designer, _ = setup(cause="skill_gap")
    context = service._context("hyp_1")
    fixture_decision = validate_decision(asyncio.run(DemoDesignFixture(context.approved.signal_id).decide(context)), context)
    assert fixture_decision.decision_type == "training" and fixture_decision.intervention_id is None
    with pytest.raises(TrainingDesignRefused) as failure:
        asyncio.run(designer.design(context.provider_view(), fixture_decision))
    assert failure.value.reason == "solution_validation_required" and runtime.calls == []
    # A decision from another run or diagnosis is refused before anything else is read.
    _, decision = handoff_decision(service, service.intervention.interventions)
    foreign = InterventionDecision.model_validate(decision.model_dump() | {"run_id": "design_other"})
    with pytest.raises(TrainingDesignRefused) as failure:
        training_intervention_from_decision(context, foreign)
    assert failure.value.reason == "intervention_mismatch"


def test_fixture_decision_cannot_drive_the_provider_designer_through_the_api():
    """A fixture intervention step beside a real designer is refused by the service with a
    fixed 409, before the designer is even asked; nothing is stored and nothing is sent."""
    service, runtime, designer, _ = setup(cause="skill_gap")
    fixture_fed = DesignService(service.diagnostics, DemoDesignFixture(service._context("hyp_1").approved.signal_id), designer)
    assert fixture_fed.controlled_fixture is False  # A real designer can never be labelled a fixture.
    prior = with_client(fixture_fed)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1")
            assert failed.status_code == 409
            assert failed.json()["detail"] == {"code": "training_design_not_permitted",
                                               "message": PASSTHROUGH_DESIGN_ERRORS["training_design_not_permitted"]}
            assert client.get("/designs/diagnoses/hyp_1").status_code == 404
    finally:
        app.state.designs = prior
    assert runtime.calls == []


def test_designer_refusal_reaches_the_client_as_422_with_fixed_text_only():
    service, runtime, _, _ = setup()

    class Mismatching:
        async def design(self, context, decision):
            raise TrainingDesignRefused("intervention_mismatch")

    service.training = Mismatching()
    prior = with_client(service)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1")
            assert failed.status_code == 422
            assert failed.json()["detail"] == {"code": "training_design_refused",
                                               "message": REFUSAL_MESSAGES["intervention_mismatch"]}
            assert client.get("/designs/diagnoses/hyp_1").status_code == 404
    finally:
        app.state.designs = prior


def test_refusal_reason_outside_the_fixed_table_becomes_a_generic_failure():
    service, _, _, _ = setup()

    class Custom:
        async def design(self, context, decision):
            raise TrainingDesignRefused("provider chosen text")

    service.training = Custom()
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "design_provider_failure"
    assert "chosen" not in str(failure.value)


def test_validated_intervention_contract_only_accepts_the_permitted_aws4_handoff():
    service, _, _, interventions = setup()
    context, decision = handoff_decision(service, interventions)
    adapted = training_intervention_from_decision(context, decision)
    record = interventions.get("hyp_1")
    assert adapted.validation_source == AWS4_VALIDATION_SOURCE
    assert (adapted.intervention_type, adapted.solution_alignment, adapted.training_design_gate) == (
        "practice_simulation", "aligned", "permitted")
    assert adapted.intervention_id == record.proposal.intervention_id
    assert adapted.solution_validation_id == record.solution_validation.solution_validation_id
    assert adapted.recommendation == record.proposal.recommendation
    assert adapted.target_change == record.proposal.target_change
    assert adapted.training_focus == TrainingFocus.SKILL
    for forged in ({"validation_source": "m5_intervention_decision"}, {"validation_source": "self_declared"},
                   {"training_design_gate": "withheld"}, {"solution_alignment": "partially_aligned"},
                   {"intervention_type": "coaching"}, {"intervention_type": "investigate_further"}):
        with pytest.raises(ValidationError):
            ValidatedTrainingIntervention(**(adapted.model_dump() | forged))
    # The approved cause never decides eligibility (AWS-4 did); it only shapes the emphasis.
    for cause in ("process_gap", "undetermined", "knowledge_gap"):
        assert ValidatedTrainingIntervention(**(adapted.model_dump() | {"cause_domain": cause})).cause_domain == cause
    from app.diagnostics.models import CauseDomain
    assert training_focus_for("practice_simulation", CauseDomain.KNOWLEDGE_GAP) == TrainingFocus.SKILL
    assert training_focus_for("training", CauseDomain.KNOWLEDGE_GAP) == TrainingFocus.KNOWLEDGE
    assert training_focus_for("training", CauseDomain.SKILL_GAP) == TrainingFocus.KNOWLEDGE_AND_SKILL
    assert training_focus_for("training", CauseDomain.PROCESS_GAP) == TrainingFocus.KNOWLEDGE_AND_SKILL


# --- E: missing operational details are surfaced, not invented ---------------------------

def test_missing_operational_details_are_surfaced_with_placeholders():
    raw = package()
    raw["practice_scenarios"][0]["beats"][1]["expected_learner_behavior"] = (
        "State the expected timing as [PLACEHOLDER:M1] and ask a confirming question.")
    raw["missing_operational_details"] = [{"id": "M1", "placeholder": "[PLACEHOLDER:M1]",
                                           "description": "The expected timing for the follow-up message was not supplied.",
                                           "needed_for": "Practice scenario P1, turn BEAT2."}]
    service, _, _, _ = setup(runtime=FakeRuntime(json.dumps(raw)))
    result = run(service)
    detail = result.training_design.missing_operational_details[0]
    assert detail.detail_id == result.run_id + "/M1" and detail.placeholder == "[PLACEHOLDER:M1]"
    assert result.alignment_trace.missing_operational_detail_ids == (detail.detail_id,)
    assert result.training_design.design_basis.supplied_operational_context == ()
    assert "[PLACEHOLDER:M1]" in result.training_design.practice_scenarios[0].beats[1].expected_learner_behavior


def test_undeclared_placeholder_or_invented_escalation_is_refused():
    undeclared = package()
    undeclared["practice_scenarios"][0]["scenario_setup"] = "Escalate per [PLACEHOLDER:M9]."
    service, runtime, _, _ = setup(runtime=FakeRuntime(json.dumps(undeclared)))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output"
    with pytest.raises(DesignError, match="No design run"):
        service.get("hyp_1")
    malformed_token = package(missing_operational_details=[{"id": "M1", "placeholder": "M1",
                                                            "description": "x", "needed_for": "y"}])
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(malformed_token), TrainingFocus.SKILL)
    blank_escalation = package()
    blank_escalation["practice_scenarios"][0]["escalation_expectation"] = "   "
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(blank_escalation), TrainingFocus.SKILL)
    unused = package(missing_operational_details=[{"id": "M1", "placeholder": "[PLACEHOLDER:M1]",
                                                  "description": "A missing fact", "needed_for": "Practice"}])
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(unused), TrainingFocus.SKILL)
    mismatched = deepcopy(undeclared)
    mismatched["practice_scenarios"][0]["scenario_setup"] = "Use [PLACEHOLDER:M2]."
    mismatched["missing_operational_details"] = [{"id": "M1", "placeholder": "[PLACEHOLDER:M2]",
                                                  "description": "A missing fact", "needed_for": "Practice"}]
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(mismatched), TrainingFocus.SKILL)
    escalation = package()
    escalation["practice_scenarios"][0]["escalation_expectation"] = "Transfer to a specialist."
    service, runtime, _, _ = setup(runtime=FakeRuntime(json.dumps(escalation)))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output" and runtime.calls


def test_supplied_operational_context_is_the_only_operational_input_and_is_recorded():
    context_facts = ("Follow-up messages are sent within the standard notification window.",)
    service, runtime, _, _ = setup(operational_context=context_facts)
    result = run(service)
    request = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
    assert request["supplied_operational_context"] == list(context_facts)
    assert result.training_design.design_basis.supplied_operational_context == context_facts


# --- F: knowledge check has exactly four options and specific feedback ------------------

@pytest.mark.parametrize("mutate", [
    lambda k: k["options"].pop(),
    lambda k: k["options"].append(deepcopy(k["options"][0]) | {"id": "K1_OPT5"}),
    lambda k: k["options"][0].update(correct=True),
    lambda k: k["options"][0].update(feedback=k["options"][1]["feedback"]),
    lambda k: k["options"][0].update(feedback=k["options"][0]["response"]),
    lambda k: k["options"][0].update(feedback="  "),
    lambda k: k.update(objective_ids=["O9"]),
    lambda k: k.update(behavior_ids=["B9"]),
])
def test_knowledge_check_structure_and_feedback_specificity(mutate):
    raw = package("knowledge")
    mutate(raw["knowledge_checks"][0])
    service, _, _, _ = setup(cause="knowledge_gap", runtime=FakeRuntime(json.dumps(raw)))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output"


def test_knowledge_check_feedback_specificity_applies_to_every_training_design():
    """The M5 structural validator, not only the Bedrock parser, enforces specific feedback."""
    service, fixture = _fixture_service()
    context = service._context("hyp_1")
    training = asyncio.run(fixture.design(context, asyncio.run(fixture.decide(context))))
    training["decision_checks"][0]["options"][1]["feedback"] = training["decision_checks"][0]["options"][0]["feedback"]
    with pytest.raises(InvalidDesignOutput, match="specific"):
        validate_training(training, context)


def _fixture_service():
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(response(bundle)))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    diagnosis.approve("hyp_1", "lead")
    fixture = DemoDesignFixture(signal.signal_id)
    return DesignService(diagnosis, fixture, fixture, controlled_fixture=True), fixture


# --- G: objectives are observable and measurable ----------------------------------------

def test_objective_carries_condition_action_and_standard():
    service, _, _, _ = setup()
    objective = run(service).training_design.objectives[0]
    assert objective.condition and objective.observable_action and objective.standard
    assert objective.measurable_outcome


@pytest.mark.parametrize("field", ["standard", "observable_action", "condition", "measurable_outcome"])
def test_objective_missing_or_blank_measurability_is_refused(field):
    missing = package()
    del missing["objectives"][0][field]
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(missing), TrainingFocus.SKILL)
    blank = package()
    blank["objectives"][0][field] = " "
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(blank), TrainingFocus.SKILL)


# --- H: practice rubric references the expected behavior ---------------------------------

def test_rubric_criteria_reference_practiced_behaviors_and_their_objectives():
    service, _, _, _ = setup()
    result = run(service)
    design = result.training_design
    objectives = {o.objective_id: o for o in design.objectives}
    for scenario in design.practice_scenarios:
        assert {c.behavior_id for c in scenario.rubric} == set(scenario.behavior_ids)
        for criterion in scenario.rubric:
            assert criterion.objective_id in scenario.objective_ids
            assert criterion.behavior_id in objectives[criterion.objective_id].behavior_ids
            assert any(criterion.behavior_id in turn.behavior_ids for turn in scenario.beats)


@pytest.mark.parametrize("mutate", [
    lambda p: p["rubric"][0].update(behavior_id="B9"),
    lambda p: p["rubric"][0].update(objective_id="O9"),
    lambda p: p["rubric"].clear(),
    lambda p: p["beats"][0].update(behavior_ids=["B9"]),
])
def test_rubric_or_turn_outside_the_practiced_behavior_is_refused(mutate):
    raw = package()
    mutate(raw["practice_scenarios"][0])
    service, _, _, _ = setup(runtime=FakeRuntime(json.dumps(raw)))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output"


# --- I: dangling and cross-run references ------------------------------------------------

@pytest.mark.parametrize("mutate", [
    lambda r: r["objectives"][0].update(behavior_ids=["B9"]),
    lambda r: r["activities"][0].update(objective_ids=["O9"]),
    lambda r: r["outline"][0].update(activity_ids=["A9"]),
    lambda r: r["practice_scenarios"][0].update(activity_id="A9"),
    lambda r: r["target_behaviors"].append({"id": "B1", "gap_reference": GAP_REFERENCE, "description": "Duplicate"}),
    lambda r: r["target_behaviors"][0].update(gap_reference="GAP-002"),
    lambda r: r["objectives"][0].update(id="other_run/O1"),
    lambda r: r["outline"][1].update(activity_ids=[]),
])
def test_dangling_duplicate_or_cross_run_references_are_refused(mutate):
    raw = package()
    mutate(raw)
    service, _, _, _ = setup(runtime=FakeRuntime(json.dumps(raw)))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output"


def test_every_stored_identifier_is_prefixed_with_this_run():
    service, _, _, _ = setup(runtime=FakeRuntime(json.dumps(package("knowledge") | {"knowledge_checks": [knowledge_check()]})))
    result = run(service)
    dumped = json.dumps(result.training_design.model_dump(mode="json"))
    for label in ("B1", "O1", "S1", "A1", "K1", "K1_OPT1", "P1", "PERSONA1", "BEAT1", "R1"):
        assert f'"{result.run_id}/{label}"' in dumped
    assert '"B1"' not in dumped and '"O1"' not in dumped


# --- J: malformed Bedrock output fails closed --------------------------------------------

@pytest.mark.parametrize("text,stop", [
    ("not json", "end_turn"),
    ("```json\n" + json.dumps(package()) + "\n```", "end_turn"),
    (json.dumps([package()]), "end_turn"),
    (json.dumps(package() | {"extra_key": "x"}), "end_turn"),
    (json.dumps({k: v for k, v in package().items() if k != "outline"}), "end_turn"),
    (json.dumps(package()), "max_tokens"),
    (json.dumps(package(performance_context="The learner failed 75% of calls.")), "end_turn"),
    (json.dumps(package(performance_context="Failed 3 of 4 evaluations.")), "end_turn"),
    ("", "end_turn"),
])
def test_malformed_or_incomplete_output_is_refused_and_not_stored(text, stop):
    service, runtime, _, _ = setup(runtime=FakeRuntime(text, stop_reason=stop))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output" and len(runtime.calls) == 1
    with pytest.raises(DesignError, match="No design run"):
        service.get("hyp_1")
    runtime.text, runtime.stop_reason = json.dumps(package()), "end_turn"
    assert run(service).training_design is not None  # A failed run stores nothing and may be retried.


def test_raw_json_rejects_duplicate_keys_and_type_coercion():
    raw = package()
    raw["activities"][0]["duration_minutes"] = "10"
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(raw), TrainingFocus.SKILL)
    raw = package()
    raw["knowledge_checks"][0]["options"][0]["correct"] = 0
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(json.dumps(raw), TrainingFocus.SKILL)
    duplicate = json.dumps(package())[:-1] + ',"performance_context":"overridden"}'
    with pytest.raises(InvalidDesignOutput):
        parse_designer_response(duplicate, TrainingFocus.SKILL)


def test_aws_client_failure_is_a_sanitized_502():
    service, _, _, _ = setup(runtime=FakeRuntime(error=RuntimeError("secret endpoint detail")))
    prior = with_client(service)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1")
            assert failed.status_code == 502
            assert failed.json()["detail"]["code"] == "design_provider_failure"
            assert "secret" not in failed.text
    finally:
        app.state.designs = prior


def test_converse_text_accepts_reasoning_blocks_but_not_tool_use():
    ok = {"stopReason": "end_turn", "output": {"message": {"content": [
        {"reasoningContent": {"reasoningText": {"text": "thinking"}}}, {"text": "{}"}]}}}
    assert converse_text(ok) == "{}"
    with pytest.raises(InvalidDesignOutput):
        converse_text({"stopReason": "end_turn", "output": {"message": {"content": [{"toolUse": {}}]}}})


# --- K: the provider cannot self-assert provenance ---------------------------------------

@pytest.mark.parametrize("forged", [
    {"provider_metadata": {"provider": "trusted", "generation_mode": "controlled_fixture"}},
    {"generation_mode": "controlled_fixture"},
    {"run_id": "design_forged"},
    {"diagnosis_id": "hyp_other"},
    {"design_basis": {"guidance_version": "forged"}},
    {"status": "aligned"},
])
def test_provider_output_cannot_assert_provenance_or_status(forged):
    service, _, _, _ = setup(runtime=FakeRuntime(json.dumps(package() | forged)))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "invalid_design_output"


def test_provenance_is_stamped_locally_from_the_installed_objects():
    service, _, designer, _ = setup()
    result = run(service)
    metadata = result.training_design.provider_metadata
    assert result.generation_mode == "provider"
    assert (metadata.provider, metadata.model, metadata.invocation_region, metadata.invocation_id) == (
        "Amazon Bedrock", designer.model_id, designer.region, "synthetic-request-id")
    assert metadata.generation_mode is None  # Never provider-asserted; the result carries the mode.
    assert result.intervention.provider_metadata.provider == "controlled fixture"  # AWS-4 fixture reasoner.
    assert result.intervention.provider_metadata.generation_mode is None
    assert design_provider_kind(service.intervention, designer) == "provider"
    with pytest.raises(DesignError, match="controlled_fixture flag disagrees"):
        DesignService(service.diagnostics, service.intervention, designer, controlled_fixture=True)


# --- L: the AWS-2 privacy boundary stays intact ------------------------------------------

def test_request_is_an_allowlisted_projection_without_rows_names_ids_or_counts():
    service, runtime, _, interventions = setup()
    context = service._context("hyp_1")
    record = interventions.get("hyp_1")
    result = run(service)
    call = runtime.calls[0]
    assert set(call) == {"modelId", "system", "messages", "inferenceConfig"}
    assert call["system"] == [{"text": SYSTEM_PROMPT}]
    request = json.loads(call["messages"][0]["content"][0]["text"])
    assert set(request) == REQUEST_KEYS and set(request["validated_intervention"]) == INTERVENTION_KEYS
    assert request["confirmed_performance_gap"]["reference"] == GAP_REFERENCE
    assert request["confirmed_performance_gap"]["qa_criterion"] == context.signal_criterion
    assert request["validated_intervention"]["intervention_type"] == "practice_simulation"
    assert request["validated_intervention"]["target_change"] == record.proposal.target_change
    serialized = json.dumps(request)
    for leak in ("Person One", "Reviewer One", "Lead One", "lead", "eval_1", "eval_2", "synthetic.xlsx", "Sheet",
                 "missed greeting", "excel_row", "evaluator_feedback", "item_id", "evaluation_id",
                 "hyp_1", context.run_id, context.approved.signal_id, "fail_count", "evaluated_results",
                 "allowed_evidence", "approved_by", "[reviewer]",
                 # AWS-4 identifiers, outcome labels, and gate stay local; only the text travels.
                 record.proposal.intervention_id, record.solution_validation.solution_validation_id,
                 "intervention_id", "solution_validation_id", "training_design_gate", "solution_alignment",
                 "aligned", "permitted", "EVID-", "SIGNAL-"):
        assert leak not in serialized, leak
    # No counts or rates travel: the only digits are the opaque references and guidance version.
    stripped = serialized.replace(GAP_REFERENCE, "").replace("INT-001", "").replace(GUIDANCE_VERSION, "")
    assert not any(character.isdigit() for character in stripped)
    assert result.training_design.design_basis.gap.diagnosis_id == "hyp_1"  # Local record keeps the IDs.


@pytest.mark.parametrize("explanation", ["Person One struggled with the closing sequence.",
                                         "Comment said: Person One missed greeting entirely",
                                         "See eval_1 row 4 in the QA sheet"])
def test_known_identifiers_and_comments_in_diagnosis_text_block_the_remote_call(explanation):
    """AWS-4 already blocks such a diagnosis before proposing. The designer keeps its own
    screen, proven here by handing it a permitted decision directly, so a future upstream
    that lets the text through still cannot reach Bedrock via AWS-5."""
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(
        response(bundle, cause_domain="skill_gap", performance_dimension="capability")))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    diagnosis.revise("hyp_1", "lead", revision(bundle, cause_domain="skill_gap", explanation=explanation), "Revised")
    diagnosis.approve("hyp_1", "lead")
    runtime = FakeRuntime()
    designer = BedrockTrainingDesigner(client=runtime, diagnostics=diagnosis)
    clean, _, _, interventions = setup()  # A permitted handoff decision from an identical, clean diagnosis.
    context = DesignService(diagnosis, UnavailableDesignProvider(), designer)._context("hyp_1")
    decision = validate_decision(decision_from_record(interventions.get("hyp_1"), context)
                                 | {"evidence_refs": [ref.model_dump() for ref in context.allowed_evidence]}, context)
    with pytest.raises(DesignError) as failure:
        asyncio.run(designer.design(context.provider_view(), decision))
    assert failure.value.code == "design_privacy_blocked" and runtime.calls == []


@pytest.mark.parametrize("fact", ["Escalate to Lead One for benefit questions.", "See eval_2 for the script.",
                                  "The workflow is documented in synthetic.xlsx."])
def test_known_identifiers_in_supplied_operational_context_block_the_remote_call(fact):
    """Operator-supplied context is not screened by AWS-4, so the designer's screen must hold."""
    service, runtime, _, _ = setup(operational_context=(fact,))
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "design_privacy_blocked" and runtime.calls == []
    with pytest.raises(DesignError, match="No design run"):
        service.get("hyp_1")


def test_designer_without_a_bound_diagnostic_service_or_with_blocked_policy_sends_nothing():
    unbound, runtime, _, _ = setup(diagnostics_for_designer=None)
    with pytest.raises(DesignError) as failure:
        run(unbound)
    assert failure.value.code == "design_privacy_blocked" and runtime.calls == []
    source, signal, bundle = prepared()
    blocked = DiagnosticService(source, BedrockReasoner())  # privacy_blocked policy, real records.
    service, runtime, _, _ = setup(diagnostics_for_designer=blocked)
    with pytest.raises(DesignError) as failure:
        run(service)
    assert failure.value.code == "design_privacy_blocked" and runtime.calls == []


def test_privacy_block_reaches_the_client_with_fixed_text_only():
    service, _, _, _ = setup(operational_context=("Escalate to Person One when unsure.",))
    prior = with_client(service)
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1")
            assert failed.status_code == 502
            assert failed.json()["detail"] == {"code": "design_privacy_blocked",
                                               "message": "Training design privacy policy blocked"}
            assert "Person" not in failed.text
    finally:
        app.state.designs = prior


def test_normal_startup_with_bedrock_enabled_installs_designer_behind_the_aws4_handoff(tmp_path):
    script = """
import json
from app.main import app
designs = app.state.designs
print(json.dumps({"training": type(designs.training).__name__,
                  "intervention": type(designs.intervention).__name__,
                  "reasoner": type(app.state.interventions.reasoner).__name__,
                  "validator": type(app.state.interventions.validator).__name__,
                  "same_intervention_service": designs.intervention.interventions is app.state.interventions,
                  "same_diagnostics": designs.training._diagnostics is app.state.diagnostics
                                      is app.state.interventions.diagnostics,
                  "fixture": designs.controlled_fixture}))
"""
    repo = Path(__file__).resolve().parents[3]
    env = {k: v for k, v in os.environ.items() if not k.startswith("COACHLENS_")}
    env |= {"PYTHONPATH": str(repo / "services" / "api"), "COACHLENS_BEDROCK_ENABLED": "true"}
    run_ = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env,
                          cwd=tmp_path, timeout=60)
    assert run_.returncode == 0, run_.stderr
    assert json.loads(run_.stdout.strip().splitlines()[-1]) == {
        "training": "BedrockTrainingDesigner", "intervention": "ValidatedInterventionHandoff",
        "reasoner": "BedrockInterventionReasoner", "validator": "BedrockSolutionValidator",
        "same_intervention_service": True, "same_diagnostics": True, "fixture": False}


def test_default_startup_installs_no_designer():
    assert isinstance(app.state.designs.training, UnavailableDesignProvider)


# --- M: existing M5 fixture path keeps working with the extended contracts ----------------

def test_controlled_fixture_result_gains_an_alignment_trace_and_revalidates():
    service, _ = _fixture_service()
    result = run(service)
    assert result.generation_mode == "controlled_fixture"
    assert result.training_design.design_basis is None
    assert result.alignment_trace.links[0].criterion_id == result.run_id + "/R1"
    DesignResult.model_validate(result.model_dump(mode="json"))
    TrainingDesign.model_validate(result.training_design.model_dump(mode="json"))


# --- N: output is structured for the AWS-6 alignment check --------------------------------

def test_alignment_trace_enumerates_every_gap_to_rubric_path():
    service, _, _, _ = setup(runtime=FakeRuntime(json.dumps(package("knowledge") | {"knowledge_checks": [knowledge_check()]})))
    result = run(service)
    design, trace = result.training_design, result.alignment_trace
    assert trace.assessment == "structural_references_only"
    assert trace.run_id == result.run_id and trace.diagnosis_id == "hyp_1"
    criteria = {(s.scenario_id, c.criterion_id) for s in design.practice_scenarios for c in s.rubric}
    assert {(link.scenario_id, link.criterion_id) for link in trace.links} == criteria
    ids = {b.behavior_id for b in design.target_behaviors} | {o.objective_id for o in design.objectives}
    ids |= {a.activity_id for a in design.activities} | {s.scenario_id for s in design.practice_scenarios}
    for link in trace.links:
        assert link.diagnosis_id == design.design_basis.gap.diagnosis_id == "hyp_1"
        assert link.intervention_run_id == design.design_basis.intervention.run_id == result.intervention.run_id
        assert {link.behavior_id, link.objective_id, link.activity_id, link.scenario_id} <= ids
    assert trace == build_alignment_trace(design, result.intervention)
    # The AWS-4 `solution_alignment` field is the only place the word appears: the training
    # design and its trace never claim the *training* is aligned, validated, or approved.
    serialized = json.dumps(result.model_dump(mode="json")).lower()
    for claim in ("validated training", "approved training"):
        assert claim not in serialized
    design_only = json.dumps({"training_design": design.model_dump(mode="json"),
                              "alignment_trace": trace.model_dump(mode="json")}).lower()
    assert "aligned" not in design_only.replace('"solution_alignment": "aligned"', "")
    assert result.intervention.solution_alignment == "aligned"  # AWS-4's judgement of the intervention.
    with pytest.raises(ValidationError):
        DesignResult.model_validate(result.model_dump(mode="json") | {"alignment_trace": None})


# --- Contract and guidance --------------------------------------------------------------

def test_system_prompt_separates_guidance_from_contract_and_carries_no_evidence():
    assert GUIDANCE_VERSION in SYSTEM_PROMPT and guidance_text() in SYSTEM_PROMPT
    assert " -> ".join(DESIGN_CHAIN) in SYSTEM_PROMPT
    assert all(principle in SYSTEM_PROMPT for principle in PRINCIPLES)
    contract = response_contract()
    assert contract in SYSTEM_PROMPT
    for key in DesignerResponse.model_fields:
        assert f'"{key}"' in contract
    assert '"options": JSON array of 4 to 4 items' in contract
    assert "[PLACEHOLDER:M1]" in SYSTEM_PROMPT
    for leak in ("EVID-", "evaluator_feedback", "excel_row", "SIGNAL-001"):
        assert leak not in SYSTEM_PROMPT


def test_request_builder_is_pure_and_bound_to_the_allowlist():
    service, _, _, interventions = setup()
    context, decision = handoff_decision(service, interventions)
    intervention = training_intervention_from_decision(context, decision)
    request = build_designer_request(intervention, context.signal_criterion)
    assert set(request) == REQUEST_KEYS and request["validated_intervention"]["training_focus"] == "skill"
    design = to_training_design(parse_designer_response(json.dumps(package()), TrainingFocus.SKILL),
                                intervention, {"provider": "Amazon Bedrock", "model": "m"})
    validated = validate_training(design, context, decision=decision)
    assert validated.design_basis.gap.observed_behavior == context.approved.diagnosis.observed_behavioral_defect
    assert validated.design_basis.intervention.intervention_id == decision.intervention_id
    forged = deepcopy(design)
    forged["design_basis"]["gap"]["observed_behavior"] = "A different gap"
    with pytest.raises(InvalidDesignOutput, match="Design basis"):
        validate_training(forged, context)
    # A basis naming another intervention or solution review than the one the run used is refused.
    for field, value in (("intervention_id", "int_other"), ("solution_validation_id", "sol_other"),
                         ("intervention_type", "training"), ("target_change", "A different change")):
        forged = deepcopy(design)
        forged["design_basis"]["intervention"][field] = value
        with pytest.raises(InvalidDesignOutput, match="AWS-4 intervention handoff"):
            validate_training(forged, context, decision=decision)
    for forged_field in ({"solution_alignment": "partially_aligned"}, {"training_design_gate": "withheld"},
                         {"validation_source": "m5_intervention_decision"}):
        forged = deepcopy(design)
        forged["design_basis"]["intervention"] |= forged_field
        with pytest.raises(InvalidDesignOutput):
            validate_training(forged, context, decision=decision)
