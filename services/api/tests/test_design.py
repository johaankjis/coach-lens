"""M5 contract tests use only synthetic QA and controlled, non-AI outputs."""

import asyncio
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.design.demo import DemoDesignFixture
from app.design.service import DesignError, DesignService
from app.design.service import UnavailableDesignProvider
from app.design.validation import InvalidDesignOutput, validate_decision, validate_training
from app.diagnostics.engine import ControlledTestReasoner, DiagnosticService
from app.main import app
from test_diagnostics import prepared, response, revision


def setup(approve=True, revised=False, alternative=None):
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(response(bundle)))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    if revised:
        diagnosis.revise("hyp_1", "lead", revision(bundle), "Observed process issue")
    if approve:
        diagnosis.approve("hyp_1", "lead")
    fixture = DemoDesignFixture(signal.signal_id if alternative is None else "other", alternative or "investigate")
    design = DesignService(diagnosis, fixture, fixture, controlled_fixture=True)
    return design, fixture


def run(design):
    return asyncio.run(design.run("hyp_1"))


def outputs():
    design, fixture = setup()
    context = design._context("hyp_1")
    decision = asyncio.run(fixture.decide(context))
    training = asyncio.run(fixture.design(context, decision))
    return context, decision, training


def test_approval_gate_and_api():
    design, _ = setup(approve=False)
    with pytest.raises(Exception, match="not been approved"):
        run(design)
    prior = app.state.designs
    app.state.designs = design
    try:
        with TestClient(app) as client:
            assert client.post("/designs/diagnoses/hyp_1").status_code == 403
            assert client.get("/designs/diagnoses/hyp_1").status_code == 403
            assert client.post("/designs/diagnoses/missing").status_code == 404
    finally:
        app.state.designs = prior


def test_original_and_revised_approval_are_used_and_immutable():
    original, _ = setup()
    first = run(original)
    assert first.status == "ready_for_alignment_review"
    assert first.generation_mode == "controlled_fixture"
    assert first.approved_diagnosis.human_revised is False
    assert first.approved_diagnosis.diagnosis.cause_domain == "undetermined"
    revised, _ = setup(revised=True)
    result = run(revised)
    assert result.approved_diagnosis.human_revised is True
    assert result.approved_diagnosis.diagnosis.cause_domain == "process_gap"
    assert "process issue" in revised._context("hyp_1").revision_rationale
    assert result.training_design is not None  # No cause-to-intervention rule.
    assert result.intervention.evidence_refs[0] in result.approved_diagnosis.diagnosis.supporting_evidence
    result.approved_diagnosis.diagnosis.missing_evidence.append("tampered")
    assert "tampered" not in revised.get("hyp_1").approved_diagnosis.diagnosis.missing_evidence
    with pytest.raises(Exception):
        result.intervention.rationale = "tampered"


@pytest.mark.parametrize("alternative,status", [("non_training", "alternative_recommended"),
                                             ("investigate", "evidence_required")])
def test_alternative_branches_do_not_call_training(alternative, status):
    design, fixture = setup(alternative=alternative)
    class ForbiddenTraining:
        async def design(self, context, decision):
            raise AssertionError("Training must not run")
    design.training = ForbiddenTraining()
    result = run(design)
    assert result.status == status and result.training_design is None
    assert result.intervention.decision_type == alternative
    assert fixture is not None


def test_idempotent_one_run_even_when_called_twice():
    design, fixture = setup()
    calls = 0
    class Counting:
        async def decide(self, context):
            nonlocal calls
            calls += 1
            return await fixture.decide(context)
    design.intervention = Counting()
    first, second = asyncio.run(_twice(design))
    assert first.run_id == second.run_id and first.created_at == second.created_at and calls == 1


async def _twice(design):
    return await asyncio.gather(design.run("hyp_1"), design.run("hyp_1"))


@pytest.mark.parametrize("change", [
    {"decision_type": "guess"}, {"diagnosis_id": "foreign"}, {"run_id": "foreign"},
    {"evidence_refs": [{"item_id": "invented", "evaluation_id": "x"}]},
    {"next_actions": [{"action_id": "foreign/N1", "title": "x", "instructions": "x"}]},
])
def test_intervention_rejects_bad_output(change):
    context, decision, _ = outputs()
    with pytest.raises(InvalidDesignOutput):
        validate_decision(decision | change, context)


@pytest.mark.parametrize("mutate", [
    lambda d: d["target_behaviors"].append(deepcopy(d["target_behaviors"][0])),
    lambda d: d["objectives"][0].update(behavior_ids=["missing"]),
    lambda d: d["activities"][0].update(objective_ids=["missing"]),
    lambda d: d["outline"][0].update(activity_ids=["missing"]),
    lambda d: d["practice_scenarios"][0].update(activity_id="missing"),
    lambda d: d["practice_scenarios"][0]["rubric"][0].update(behavior_id="missing"),
    lambda d: d["target_behaviors"][0].update(diagnosis_id="foreign"),
    lambda d: d["objectives"][0].update(objective_id="foreign/O1"),
    lambda d: d["practice_scenarios"][0]["persona"].update(persona_id="foreign/P1"),
    lambda d: d["decision_checks"][0]["options"].pop(),
])
def test_training_reference_integrity(mutate):
    context, _, training = outputs()
    mutate(training)
    with pytest.raises(InvalidDesignOutput):
        validate_training(training, context)


def test_provider_failure_and_malformed_are_safe_and_not_stored():
    design, _ = setup()
    class Broken:
        async def decide(self, context):
            raise RuntimeError("secret provider detail")
    design.intervention = Broken()
    prior = app.state.designs
    app.state.designs = design
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1")
            assert failed.status_code == 502
            assert "secret" not in failed.text
            assert client.get("/designs/diagnoses/hyp_1").status_code == 404
            design.intervention = type("Bad", (), {"decide": lambda self, context: _bad()})()
            malformed = client.post("/designs/diagnoses/hyp_1")
            assert malformed.status_code == 502
            assert malformed.json()["detail"]["code"] == "invalid_design_output"
    finally:
        app.state.designs = prior


def test_unavailable_provider_is_503_not_a_fake_design():
    design, _ = setup()
    unavailable = UnavailableDesignProvider()
    design.intervention = unavailable
    prior = app.state.designs
    app.state.designs = design
    try:
        with TestClient(app) as client:
            result = client.post("/designs/diagnoses/hyp_1")
            assert result.status_code == 503
            assert result.json()["detail"]["code"] == "design_provider_unavailable"
            assert client.get("/designs/diagnoses/hyp_1").status_code == 404
    finally:
        app.state.designs = prior


async def _bad():
    return {"decision_type": "training"}


def test_provider_owned_object_cannot_mutate_store():
    design, fixture = setup()
    captured = {}
    class Mutable:
        async def decide(self, context):
            captured["raw"] = await fixture.decide(context)
            return captured["raw"]
    design.intervention = Mutable()
    result = run(design)
    captured["raw"]["rationale"] = "changed after storage"
    assert design.get("hyp_1").intervention.rationale == result.intervention.rationale


def test_training_branch_requires_valid_artifacts_and_can_retry_after_failure():
    design, fixture = setup()
    class MissingTraining:
        async def design(self, context, decision):
            return None
    design.training = MissingTraining()
    with pytest.raises(DesignError) as error:
        run(design)
    assert error.value.code == "invalid_design_output"
    with pytest.raises(DesignError, match="No design run"):
        design.get("hyp_1")
    design.training = fixture
    assert run(design).training_design is not None


def test_result_contract_forbids_training_on_alternative_branches():
    from app.design.models import DesignResult
    training, _ = setup()
    saved = run(training).model_dump()
    with pytest.raises(ValidationError):
        DesignResult.model_validate(saved | {"training_design": None})
    for kind, status in (("non_training", "alternative_recommended"),
                         ("investigate", "evidence_required")):
        alternative, _ = setup(alternative=kind)
        saved = run(alternative).model_dump()
        with pytest.raises(ValidationError):
            DesignResult.model_validate(saved | {"training_design": run(training).training_design.model_dump()})
        assert saved["status"] == status


def test_normalizes_constructed_model_against_real_validation():
    context, decision, _ = outputs()
    from app.design.models import InterventionDecision
    forged = InterventionDecision.model_construct(**(decision | {"decision_type": "fake"}))
    with pytest.raises(InvalidDesignOutput):
        validate_decision(forged, context)
