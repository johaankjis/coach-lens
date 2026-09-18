"""M5 review-added invariants: gate authority, provider trust, coverage, privacy, demo safety.

Synthetic QA rows and controlled non-AI outputs only.
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

from app.design.demo import DemoDesignFixture
from app.design.models import (InterventionDecision, NextAction, Objective, REDACTED_REVIEWER,
                               TrainingDesign)
from app.design.service import DesignError, DesignService, UnavailableDesignProvider
from app.design.validation import InvalidDesignOutput, validate_decision, validate_training
from app.diagnostics.engine import (ControlledTestReasoner, DiagnosticService, ProviderOutputError,
                                    validate_provider_output)
from app.diagnostics.models import ProviderMetadata
from app.main import app
from test_diagnostics import prepared, ref, response, revision


def build(*, approve=True, revised=False):
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(response(bundle)))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    if revised:
        diagnosis.revise("hyp_1", "lead", revision(bundle), "Reviewer saw a process issue")
    if approve:
        diagnosis.approve("hyp_1", "lead")
    fixture = DemoDesignFixture(signal.signal_id)
    return DesignService(diagnosis, fixture, fixture, controlled_fixture=True), fixture, bundle


def artifacts(design, fixture):
    context = design._context("hyp_1")
    decision = asyncio.run(fixture.decide(context))
    return context, decision, asyncio.run(fixture.design(context, decision))


# --- Q1: approved diagnosis is the only authority --------------------------------------

def test_approved_revision_replaces_superseded_provider_citation_and_cause():
    design, fixture, bundle = build(revised=True)
    context = design._context("hyp_1")
    assert context.approved.human_revised is True
    assert type(context.approved.diagnosis).__name__ == "HumanRevision"
    assert context.approved.diagnosis.cause_domain == "process_gap"
    assert context.revision_rationale == "Reviewer saw a process issue"
    # The superseded provider hypothesis cited row 0; the approved revision cites row 1.
    superseded = ref(bundle, 0)
    assert all(r.item_id != superseded["item_id"] for r in context.allowed_evidence)
    decision = asyncio.run(fixture.decide(context)) | {"evidence_refs": [superseded]}
    with pytest.raises(InvalidDesignOutput, match="outside approved diagnosis"):
        validate_decision(decision, context)


# --- Q5: provider output is untrusted, even when nested -------------------------------

def test_nested_prebuilt_models_are_revalidated_not_trusted():
    design, fixture, _ = build()
    context, decision, training = artifacts(design, fixture)
    hidden = NextAction.model_construct(action_id=context.run_id + "/N1", title="", instructions="x")
    with pytest.raises(InvalidDesignOutput):
        validate_decision(decision | {"next_actions": [hidden]}, context)
    oversized = ProviderMetadata.model_construct(provider="", model="m" * 10_000)
    with pytest.raises(InvalidDesignOutput):
        validate_decision(decision | {"provider_metadata": oversized}, context)


def test_provider_cannot_retain_a_reference_into_the_stored_training_design():
    design, fixture, _ = build()

    class Retaining:
        async def design(self, context, decision):
            raw = await fixture.design(context, decision)
            self.shared = [context.run_id + "/B1"]
            raw["objectives"] = [Objective.model_construct(objective_id=context.run_id + "/O1",
                                                           behavior_ids=self.shared,
                                                           measurable_outcome="original")]
            return raw

    retaining = Retaining()
    design.training = retaining
    stored = asyncio.run(design.run("hyp_1"))
    retaining.shared.append("injected/after/return")
    assert design.get("hyp_1").training_design.objectives[0].behavior_ids == (stored.run_id + "/B1",)
    assert isinstance(stored.training_design.objectives[0].behavior_ids, tuple)


def test_m3_boundary_rejects_nested_prebuilt_models_too():
    _, _, bundle = prepared()
    raw = response(bundle) | {"provider_metadata": ProviderMetadata.model_construct(provider="", model=None)}
    with pytest.raises(ProviderOutputError):
        validate_provider_output(raw, bundle)


def test_provider_lists_are_bounded():
    design, fixture, _ = build()
    context, decision, training = artifacts(design, fixture)
    with pytest.raises(InvalidDesignOutput):
        validate_decision(decision | {"risks": ["r"] * 201}, context)
    huge = deepcopy(training)
    huge["practice_scenarios"][0]["debrief_prompts"] = ["q"] * 201
    with pytest.raises(InvalidDesignOutput):
        validate_training(huge, context)


def test_provider_raised_design_error_text_never_reaches_the_client():
    design, _, _ = build()

    class Leaky:
        async def decide(self, context):
            raise DesignError("custom_code", "internal provider detail")

    design.intervention = Leaky()
    prior = app.state.designs
    app.state.designs = design
    try:
        with TestClient(app) as client:
            failed = client.post("/designs/diagnoses/hyp_1")
            assert failed.status_code == 502
            assert failed.json()["detail"] == {"code": "design_provider_failure",
                                               "message": "Design provider failed"}
    finally:
        app.state.designs = prior


def test_provider_output_cannot_set_generation_mode_or_status():
    design, fixture, _ = build()
    context, decision, _ = artifacts(design, fixture)
    for forged in ({"generation_mode": "provider"}, {"status": "aligned"}):
        with pytest.raises(InvalidDesignOutput):
            validate_decision(decision | forged, context)
    assert asyncio.run(design.run("hyp_1")).generation_mode == "controlled_fixture"


def test_provider_metadata_generation_mode_cannot_be_asserted_by_design_provider():
    """The shared `ProviderMetadata.generation_mode` is service-assigned in M3 and unused in M5;
    a design provider or fixture may not describe itself through it either."""
    design, fixture, _ = build()
    context, decision, training = artifacts(design, fixture)
    for mode in ("provider", "controlled_fixture"):
        forged_metadata = decision["provider_metadata"] | {"generation_mode": mode}
        with pytest.raises(InvalidDesignOutput, match="generation mode"):
            validate_decision(decision | {"provider_metadata": forged_metadata}, context)
        with pytest.raises(InvalidDesignOutput, match="generation mode"):
            validate_training(training | {"provider_metadata": forged_metadata}, context)
    assert validate_decision(decision, context).provider_metadata.generation_mode is None
    assert asyncio.run(design.run("hyp_1")).generation_mode == "controlled_fixture"


def test_provider_metadata_is_required_provenance():
    design, fixture, _ = build()
    context, decision, training = artifacts(design, fixture)
    with pytest.raises(InvalidDesignOutput):
        validate_decision({k: v for k, v in decision.items() if k != "provider_metadata"}, context)
    with pytest.raises(InvalidDesignOutput):
        validate_training({k: v for k, v in training.items() if k != "provider_metadata"}, context)
    assert validate_decision(decision, context).provider_metadata.provider == "m5-demo-fixture"


# --- Q4/Q7/Q9: coverage is reference integrity, not pedagogy --------------------------

def mutate(training, change):
    copy = deepcopy(training)
    change(copy)
    return copy


@pytest.mark.parametrize("change,message", [
    (lambda t: t["outline"][1].update(activity_ids=[]), "appear in the training outline"),
    (lambda t: (t["target_behaviors"].append({"behavior_id": t["run_id"] + "/B2", "diagnosis_id": "hyp_1",
                                              "description": "Second behavior"}),
                t["objectives"][0].update(behavior_ids=[t["run_id"] + "/B1", t["run_id"] + "/B2"]),
                t["practice_scenarios"][0].update(behavior_ids=[t["run_id"] + "/B1", t["run_id"] + "/B2"])),
     "no rubric criterion"),
    (lambda t: (t["target_behaviors"].append({"behavior_id": t["run_id"] + "/B2", "diagnosis_id": "hyp_1",
                                              "description": "Second behavior"}),
                t["objectives"][0].update(behavior_ids=[t["run_id"] + "/B1", t["run_id"] + "/B2"])),
     "needs hands-on practice"),
])
def test_training_coverage_gaps_are_rejected(change, message):
    design, fixture, _ = build()
    context, _, training = artifacts(design, fixture)
    with pytest.raises(InvalidDesignOutput, match=message):
        validate_training(mutate(training, change), context)


def test_structurally_valid_but_absurd_plan_is_only_ready_for_alignment_review():
    """M5 proves reference integrity. Pedagogical alignment is M6's independent job."""
    design, fixture, _ = build()

    class Absurd:
        async def design(self, context, decision):
            raw = await fixture.design(context, decision)
            raw["target_behaviors"][0]["description"] = "Demonstrate empathy"
            raw["objectives"][0]["measurable_outcome"] = "Use empathetic language"
            raw["activities"][0]["purpose"] = "Tone role-play"
            raw["practice_scenarios"][0]["rubric"][0]["observable_success"] = "Friendly tone"
            return raw

    design.training = Absurd()
    result = asyncio.run(design.run("hyp_1"))  # Structurally valid, so accepted.
    assert result.status == "ready_for_alignment_review"
    serialized = json.dumps(result.model_dump(mode="json")).lower()
    for claim in ("aligned", "validated training", "approved training", "recommended by"):
        assert claim not in serialized


# --- Q17: provider input is minimized ---------------------------------------------------

def test_provider_input_omits_reviewer_identity_rows_and_lineage():
    design, fixture, _ = build(revised=True)
    seen = {}

    class Recording:
        async def decide(self, context):
            seen["input"] = context
            return await fixture.decide(context)

    design.intervention = Recording()
    result = asyncio.run(design.run("hyp_1"))
    provider_input = seen["input"]
    assert provider_input.approved.approved_by == REDACTED_REVIEWER
    assert result.approved_diagnosis.approved_by == "lead"  # Stored provenance is intact.
    serialized = json.dumps(provider_input.model_dump(mode="json"))
    for leak in ("lead", "Person One", "Reviewer One", "Lead One", "synthetic.xlsx",
                 "missed greeting", "excel_row", "evaluator_feedback"):
        assert leak not in serialized
    assert set(provider_input.model_dump()) == {"run_id", "approved", "signal_criterion", "signal_fail_count",
                                                "signal_evaluated_results", "allowed_evidence",
                                                "revision_rationale"}


# --- Q18: demo safety -------------------------------------------------------------------

def test_normal_startup_installs_no_design_provider():
    assert isinstance(app.state.designs.intervention, UnavailableDesignProvider)
    assert isinstance(app.state.designs.training, UnavailableDesignProvider)
    assert app.state.designs.controlled_fixture is False


def test_demo_script_refuses_a_configured_evaluations_path(tmp_path):
    records = tmp_path / "evaluations.jsonl"
    records.write_text("")
    repo = Path(__file__).resolve().parents[3]
    env = os.environ | {"PYTHONPATH": str(repo / "services" / "api"),
                        "COACHLENS_API_DIAGNOSTIC_EVALUATIONS_PATH": str(records)}
    run = subprocess.run([sys.executable, str(repo / "scripts" / "run_m4_demo.py")],
                         capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60)
    assert run.returncode == 1
    assert "refuses a real evaluations path" in run.stderr


def test_result_json_uses_intervention_and_training_provenance():
    design, _, _ = build()
    payload = asyncio.run(design.run("hyp_1")).model_dump(mode="json")
    assert payload["intervention"]["provider_metadata"] == {"provider": "m5-demo-fixture", "model": None}
    assert payload["training_design"]["provider_metadata"] == {"provider": "m5-demo-fixture", "model": None}
    InterventionDecision.model_validate(payload["intervention"])
    TrainingDesign.model_validate(payload["training_design"])
