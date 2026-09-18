"""AWS-4 -> AWS-5 integration. Synthetic QA rows, controlled AWS-4 fixtures, a fake Converse
runtime for the AWS-5 designer, no AWS.

Case labels A-P follow the integration test list. The pipeline under test is the real one:

    human-validated diagnosis -> AWS-4 Intervention Reasoner -> AWS-4 Solution Validator
      -> AWS-4 DesignHandoff -> ValidatedInterventionHandoff -> AWS-5 BedrockTrainingDesigner

AWS-4 decides whether training design may proceed; AWS-5 decides how.
"""

import asyncio
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.design.bedrock import BedrockTrainingDesigner, REQUEST_KEYS
from app.design.demo import DemoDesignFixture
from app.design.models import AWS4_VALIDATION_SOURCE, InterventionDecision
from app.design.service import (PASSTHROUGH_DESIGN_ERRORS, DesignError, DesignService,
                                UnavailableDesignProvider, design_provider_kind, is_aws4_handoff,
                                training_design_permitted)
from app.design.validation import InvalidDesignOutput, validate_decision
from app.diagnostics.engine import ControlledTestReasoner, DiagnosticService
from app.interventions.demo import DemoInterventionFixture, DemoSolutionFixture
from app.interventions.handoff import ValidatedInterventionHandoff, decision_from_record
from app.interventions.service import (ControlledInterventionReasoner, ControlledSolutionValidator,
                                       InterventionService)
from app.main import app
from app.pipeline import build_pipeline, install_pipeline
from app.results_cx import demo
from test_aws4_interventions import intervention_response, solution_response
from test_aws5_training_designer import FakeRuntime, package, solution_for
from test_diagnostics import prepared, response, revision
from test_results_cx_demo import generated_sources


TRAINING_TYPES = ("training", "practice_simulation")
NON_TRAINING_TYPES = ("coaching", "process_correction", "investigate_further")
QUESTIONED = ("partially_aligned", "misaligned", "insufficient_evidence")


class ForbiddenDesigner:
    """A provider-looking designer that must never be reached."""

    async def design(self, context, decision):
        raise AssertionError("AWS-5 provider must not be invoked")


def approved(cause="skill_gap", *, revised=False):
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(
        response(bundle, cause_domain=cause, performance_dimension="capability", missing_evidence=[])))
    asyncio.run(diagnosis.diagnose(signal.signal_id))
    if revised:
        diagnosis.revise("hyp_1", "lead", revision(bundle, cause_domain=cause), "Reviewer revised the cause")
    diagnosis.approve("hyp_1", "lead")
    return diagnosis, signal


def pipeline(intervention_type="practice_simulation", alignment="aligned", *, cause="skill_gap",
             revised=False, runtime=None, designer=None, validate=True):
    diagnosis, signal = approved(cause, revised=revised)
    changes = {"intervention_type": intervention_type}
    if intervention_type == "investigate_further":
        changes["missing_evidence"] = ["Evaluator observations of the closing sequence"]
    if revised:
        changes["evidence_reference_ids"] = ["EVID-002"]
    interventions = InterventionService(diagnosis, None, ControlledInterventionReasoner(intervention_response(**changes)),
                                        ControlledSolutionValidator(solution_for(alignment)))
    asyncio.run(interventions.propose("hyp_1"))
    if validate:
        asyncio.run(interventions.validate_solution("hyp_1"))
    runtime = runtime or FakeRuntime()
    designer = designer or BedrockTrainingDesigner(client=runtime, diagnostics=diagnosis)
    designs = DesignService(diagnosis, ValidatedInterventionHandoff(interventions), designer)
    return diagnosis, interventions, designs, runtime, signal


# --- A/B: aligned training and practice interventions reach the AWS-5 provider ----------------

@pytest.mark.parametrize("intervention_type", TRAINING_TYPES)
def test_case_ab_aligned_training_or_practice_invokes_the_aws5_provider(intervention_type):
    _, interventions, designs, runtime, _ = pipeline(intervention_type)
    record = interventions.get("hyp_1")
    assert record.handoff.training_design_gate == "permitted" and record.status == "solution_validated"
    result = asyncio.run(designs.run("hyp_1"))
    assert len(runtime.calls) == 1
    assert result.status == "ready_for_alignment_review" and result.generation_mode == "provider"
    assert result.training_design is not None and result.alignment_trace is not None
    assert result.intervention.intervention_type == intervention_type
    assert result.intervention.training_design_gate == "permitted"
    assert result.intervention.solution_alignment == "aligned"
    # The designer received the AWS-4 intervention text, not a cause-derived summary.
    request = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
    assert set(request) == REQUEST_KEYS
    assert request["validated_intervention"]["intervention_type"] == intervention_type
    assert request["validated_intervention"]["recommendation"] == record.proposal.recommendation
    assert request["validated_intervention"]["target_change"] == record.proposal.target_change
    # Repeat runs are idempotent and never call the provider again.
    assert asyncio.run(designs.run("hyp_1")) == result and len(runtime.calls) == 1


def test_case_a_human_approved_diagnosis_is_the_only_input_and_revision_flows_through():
    """A human revision is what AWS-4 reasoned from and what AWS-5 designs from."""
    _, interventions, designs, runtime, _ = pipeline("training", revised=True, cause="skill_gap")
    result = asyncio.run(designs.run("hyp_1"))
    assert result.approved_diagnosis.human_revised is True
    basis = result.training_design.design_basis
    assert basis.gap.human_revised is True and basis.gap.cause_domain == "skill_gap"
    request = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
    assert request["confirmed_performance_gap"]["human_revised"] is True
    assert request["confirmed_performance_gap"]["observed_behavior"] == "Two failed greeting checks"
    assert "Available facts establish failures" not in json.dumps(request)  # Superseded provider text.


# --- C/D/E: questioned training interventions never reach the provider ------------------------

@pytest.mark.parametrize("alignment", QUESTIONED)
@pytest.mark.parametrize("intervention_type", TRAINING_TYPES)
def test_case_cde_questioned_training_is_withheld_and_the_provider_is_not_invoked(intervention_type, alignment):
    _, interventions, designs, runtime, _ = pipeline(intervention_type, alignment, designer=ForbiddenDesigner())
    record = interventions.get("hyp_1")
    assert record.status == "solution_questioned"
    assert record.solution_validation.alignment_outcome == alignment
    assert record.handoff.training_design_gate == "withheld"
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.run("hyp_1"))
    assert error.value.code == "training_design_withheld"
    assert str(error.value) == PASSTHROUGH_DESIGN_ERRORS["training_design_withheld"]
    with pytest.raises(DesignError, match="No design run"):
        designs.get("hyp_1")
    assert runtime.calls == []


def test_case_c_partially_aligned_is_solution_questioned_not_a_weaker_yes():
    _, interventions, _, _, _ = pipeline("training", "partially_aligned")
    record = interventions.get("hyp_1")
    assert record.solution_validation.solution_status == "solution_questioned"
    assert record.handoff.solution_status == "solution_questioned"
    assert record.handoff.training_design_gate == "withheld"


# --- F/G/H: non-training interventions produce no training artifact ---------------------------

@pytest.mark.parametrize("intervention_type,status", [
    ("process_correction", "alternative_recommended"), ("coaching", "alternative_recommended"),
    ("investigate_further", "evidence_required")])
def test_case_fgh_aligned_non_training_interventions_produce_no_training_package(intervention_type, status):
    _, interventions, designs, runtime, _ = pipeline(intervention_type, designer=ForbiddenDesigner())
    record = interventions.get("hyp_1")
    assert record.status == "solution_validated" and record.handoff.training_design_gate == "not_applicable"
    result = asyncio.run(designs.run("hyp_1"))
    assert result.status == status and result.training_design is None and result.alignment_trace is None
    assert result.intervention.intervention_type == intervention_type
    assert result.intervention.training_design_gate == "not_applicable"
    assert result.intervention.next_actions[1].instructions == record.proposal.target_change
    assert runtime.calls == []


@pytest.mark.parametrize("intervention_type", NON_TRAINING_TYPES)
def test_case_fgh_questioned_non_training_interventions_stop_before_m5(intervention_type):
    _, _, designs, runtime, _ = pipeline(intervention_type, "partially_aligned", designer=ForbiddenDesigner())
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.run("hyp_1"))
    assert error.value.code == "solution_questioned" and runtime.calls == []


# --- I: stale or cross-run handoff is rejected --------------------------------------------------

def test_case_i_stale_or_cross_run_handoff_is_rejected():
    _, interventions, designs, runtime, _ = pipeline("training")
    context = designs._context("hyp_1")
    record = interventions.get("hyp_1")
    # A decision projected for another run or another diagnosis fails M5 provenance.
    for change in ({"run_id": "design_other"}, {"diagnosis_id": "hyp_other"}):
        with pytest.raises(InvalidDesignOutput, match="provenance"):
            validate_decision(decision_from_record(record, context) | change, context)
    # A handoff whose stored record describes a different validated diagnosis is stale.
    changed = context.approved.diagnosis.model_copy(update={"explanation": "A different account"})
    foreign = context.provider_view().model_copy(update={"approved": context.approved.model_copy(
        update={"diagnosis": changed})})
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.intervention.decide(foreign))
    assert error.value.code == "intervention_stale"
    # Proposal without a solution review, and no proposal at all, both stop before the designer.
    _, _, unvalidated, unvalidated_runtime, _ = pipeline("training", validate=False)
    with pytest.raises(DesignError) as error:
        asyncio.run(unvalidated.run("hyp_1"))
    assert error.value.code == "solution_not_validated" and unvalidated_runtime.calls == []
    diagnosis, _ = approved()
    empty = DesignService(diagnosis, ValidatedInterventionHandoff(InterventionService(
        diagnosis, None, ControlledInterventionReasoner({}), ControlledSolutionValidator({}))),
        BedrockTrainingDesigner(client=runtime, diagnostics=diagnosis))
    with pytest.raises(DesignError) as error:
        asyncio.run(empty.run("hyp_1"))
    assert error.value.code == "intervention_not_proposed" and runtime.calls == []


# --- J/K: the design basis carries the AWS-4 identifiers and the local validation source ------

def test_case_jk_design_basis_traces_to_the_aws4_intervention_and_solution_validation():
    _, interventions, designs, _, _ = pipeline("practice_simulation")
    record = interventions.get("hyp_1")
    result = asyncio.run(designs.run("hyp_1"))
    basis = result.training_design.design_basis
    assert basis.gap.diagnosis_id == record.hypothesis_id == result.approved_diagnosis.hypothesis_id
    assert basis.intervention.intervention_id == record.proposal.intervention_id == result.intervention.intervention_id
    assert (basis.intervention.solution_validation_id == record.solution_validation.solution_validation_id
            == result.intervention.solution_validation_id)
    assert basis.intervention.intervention_type == "practice_simulation"
    assert basis.intervention.solution_alignment == "aligned" and basis.intervention.training_design_gate == "permitted"
    assert basis.intervention.summary == record.proposal.recommendation
    assert basis.intervention.target_change == record.proposal.target_change
    assert basis.intervention.validation_source == AWS4_VALIDATION_SOURCE  # Stamped locally, never by the model.
    assert basis.intervention.run_id == result.run_id == result.alignment_trace.links[0].intervention_run_id
    assert record.handoff.human_reviewed_intervention is False
    serialized = json.dumps(result.model_dump(mode="json")).lower()
    for claim in ("validated training", "approved training"):
        assert claim not in serialized


# --- L/O: the retired cause-derived route and the fixture-only path -----------------------------

def test_case_l_provider_designer_cannot_be_driven_by_a_fixture_decision():
    diagnosis, signal = approved("skill_gap")
    runtime = FakeRuntime()
    fixture_fed = DesignService(diagnosis, DemoDesignFixture(signal.signal_id),
                                BedrockTrainingDesigner(client=runtime, diagnostics=diagnosis))
    with pytest.raises(DesignError) as error:
        asyncio.run(fixture_fed.run("hyp_1"))
    assert error.value.code == "training_design_not_permitted" and runtime.calls == []
    with pytest.raises(DesignError, match="No design run"):
        fixture_fed.get("hyp_1")
    # The gate reads the handoff object and every AWS-4 field; none alone is permission.
    context = fixture_fed._context("hyp_1")
    fixture_decision = validate_decision(asyncio.run(fixture_fed.intervention.decide(context)), context)
    assert not training_design_permitted(fixture_decision) and not is_aws4_handoff(fixture_fed.intervention)
    _, interventions, designs, _, _ = pipeline("training")
    decision = validate_decision(decision_from_record(interventions.get("hyp_1"), context), context)
    assert training_design_permitted(decision) and is_aws4_handoff(designs.intervention)
    for weakened in ({"solution_validation_id": None, "solution_alignment": None,
                      "training_design_gate": "awaiting_solution_validation"},
                     {"training_design_gate": None}, {"intervention_id": None},
                     {"recommendation": None}, {"target_change": None}):
        with pytest.raises(ValueError):
            InterventionDecision.model_validate(decision.model_dump() | weakened)


def test_partial_aws4_provenance_cannot_validate_as_a_fixture_decision():
    _, interventions, designs, _, _ = pipeline("training")
    context = designs._context("hyp_1")
    integrated = decision_from_record(interventions.get("hyp_1"), context)
    fixture = dict(integrated)
    for field in ("intervention_type", "recommendation", "target_change", "solution_alignment",
                  "intervention_id", "solution_validation_id", "training_design_gate"):
        fixture[field] = None
    assert InterventionDecision.model_validate(fixture).intervention_id is None
    for field in ("intervention_type", "recommendation", "target_change", "solution_alignment",
                  "intervention_id", "solution_validation_id", "training_design_gate"):
        with pytest.raises(ValueError):
            InterventionDecision.model_validate(fixture | {field: integrated[field]})


def test_case_o_fixture_path_is_fixture_only_and_the_m4_demo_stays_on_it():
    diagnosis, signal = approved("skill_gap")
    fixture = DemoDesignFixture(signal.signal_id)
    assert fixture.controlled_fixture is True
    with pytest.raises(DesignError, match="controlled_fixture flag disagrees"):
        DesignService(diagnosis, fixture, fixture)  # A fixture may not pose as a provider.
    with pytest.raises(DesignError, match="controlled_fixture flag disagrees"):
        DesignService(diagnosis, fixture, BedrockTrainingDesigner(client=FakeRuntime(), diagnostics=diagnosis),
                      controlled_fixture=True)  # A provider may not pose as a fixture.
    result = asyncio.run(DesignService(diagnosis, fixture, fixture, controlled_fixture=True).run("hyp_1"))
    assert result.generation_mode == "controlled_fixture" and result.training_design.design_basis is None
    assert result.intervention.intervention_id is None and result.intervention.training_design_gate is None
    # The synthetic M4 demo feeds the M5 fixture through the AWS-4 handoff, never a provider.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("m4demo", Path(__file__).resolve().parents[3] / "scripts" / "run_m4_demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.fixture_evaluations()
    from app.diagnostics.engine import detect_signals
    resolution = next(s for s in detect_signals(rows) if s.criterion == "Resolution summary clarity")
    demo_diagnosis = DiagnosticService(rows, module.DemoFixtureReasoner(resolution.signal_id))
    demo_interventions = InterventionService(demo_diagnosis, None, DemoInterventionFixture(), DemoSolutionFixture())
    demo_designs = DesignService(demo_diagnosis, ValidatedInterventionHandoff(demo_interventions),
                                 DemoDesignFixture(resolution.signal_id), controlled_fixture=True)
    assert design_provider_kind(demo_designs.intervention, demo_designs.training) == "controlled_fixture"
    hypothesis_id = asyncio.run(demo_diagnosis.diagnose(resolution.signal_id)).provider_hypothesis.hypothesis_id
    demo_diagnosis.approve(hypothesis_id, "demo")
    asyncio.run(demo_interventions.propose(hypothesis_id))
    asyncio.run(demo_interventions.validate_solution(hypothesis_id))
    demo_result = asyncio.run(demo_designs.run(hypothesis_id))
    assert demo_result.generation_mode == "controlled_fixture" and demo_result.training_design is not None
    assert demo_result.intervention.intervention_type == "practice_simulation"
    assert demo_result.intervention.training_design_gate == "permitted"


# --- M/N: privacy boundaries -------------------------------------------------------------------

def test_case_mn_aws4_and_aws5_wires_carry_no_rows_names_ids_or_counts_end_to_end():
    _, interventions, designs, runtime, _ = pipeline("training")
    context = designs._context("hyp_1")
    record = interventions.get("hyp_1")
    asyncio.run(designs.run("hyp_1"))
    aws4_wires = [json.dumps(r) for r in (interventions.reasoner.requests[0], interventions.validator.requests[0])]
    aws5_wire = json.dumps(runtime.calls[0])
    for wire in (*aws4_wires, aws5_wire):
        for forbidden in ("Person One", "Reviewer One", "Lead One", "lead", "eval_1", "eval_2", "ev_", "sig_",
                          "synthetic.xlsx", "Sheet", "source_lineage", "evaluator_feedback", "missed greeting",
                          "agent_name", "qa_name", "team_leader", "approved_by", "hypothesis_id", "hyp_1",
                          context.run_id, record.proposal.intervention_id,
                          record.solution_validation.solution_validation_id):
            assert forbidden not in wire, forbidden
    # AWS-4 sends the structured population; AWS-5 sends neither rows, references, nor counts.
    aws5_request = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
    aws5_body = json.dumps(aws5_request)
    assert "evidence_items" in aws4_wires[0] and "evidence_items" not in aws5_wire
    assert "failed_criterion_result_count" in aws4_wires[0] and "count" not in aws5_body
    assert set(aws5_request) == REQUEST_KEYS and "EVID-" not in aws5_wire and "SIGNAL-" not in aws5_wire
    assert not any(character.isdigit() for character in
                   aws5_body.replace("GAP-001", "").replace("INT-001", "").replace("resultscx-design-guidance/2", ""))


def test_case_n_aws5_provider_is_gated_by_the_diagnostic_policy_even_after_an_aligned_handoff():
    from app.diagnostics.bedrock import BedrockReasoner
    diagnosis, _ = approved()
    blocked = DiagnosticService(*[prepared()[0]], BedrockReasoner())  # privacy_blocked policy.
    _, _, designs, runtime, _ = pipeline("training", designer=BedrockTrainingDesigner(client=FakeRuntime(),
                                                                                    diagnostics=blocked))
    with pytest.raises(DesignError) as error:
        asyncio.run(designs.run("hyp_1"))
    assert error.value.code == "design_privacy_blocked"
    assert designs.training._client.calls == []


def test_case_m_real_results_cx_mode_installs_one_consistent_graph_with_no_fixtures(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    for enabled in (False, True):
        monkeypatch.setattr(demo, "get_settings", lambda enabled=enabled: Settings(bedrock_enabled=enabled, _env_file=None))
        prior = (app.state.diagnostics, app.state.evidence_validations, app.state.interventions,
                 app.state.designs, app.state.demo_mode)
        try:
            demo.install_results_cx_demo(app, trusted)
            state = app.state
            assert state.evidence_validations.diagnostics is state.diagnostics
            assert state.interventions.diagnostics is state.diagnostics
            assert state.interventions.evidence_validations is state.evidence_validations
            assert state.designs.diagnostics is state.diagnostics
            assert isinstance(state.designs.intervention, ValidatedInterventionHandoff)
            assert state.designs.intervention.interventions is state.interventions
            assert not getattr(state.interventions.reasoner, "controlled_fixture", False)
            assert not getattr(state.designs.training, "controlled_fixture", False)
            if enabled:
                assert isinstance(state.designs.training, BedrockTrainingDesigner)
                assert state.designs.training._diagnostics is state.diagnostics
                assert state.diagnostics.reasoner.remote_invocation_policy == "real_minimized"
            else:
                assert isinstance(state.designs.training, UnavailableDesignProvider)
            mode = TestClient(app).get("/diagnostics/mode").json()
            expected = "provider" if enabled else "unavailable"
            assert (mode["design_provider"], mode["intervention_provider"], mode["solution_validator"]) == (
                expected, expected, expected)
        finally:
            (app.state.diagnostics, app.state.evidence_validations, app.state.interventions,
             app.state.designs, app.state.demo_mode) = prior


def test_pipeline_builder_is_the_single_wiring_for_both_startup_paths():
    diagnosis, _ = approved()
    built = build_pipeline(diagnosis, Settings(bedrock_enabled=True, _env_file=None))
    assert built.designs.intervention.interventions is built.interventions
    assert built.interventions.evidence_validations is built.evidence_validations
    assert built.designs.training._diagnostics is diagnosis is built.evidence_validations.diagnostics

    class State:
        pass

    class Holder:
        state = State()

    holder = Holder()
    installed = install_pipeline(holder, diagnosis, Settings(_env_file=None))
    assert holder.state.designs is installed.designs and holder.state.interventions is installed.interventions
    assert isinstance(holder.state.designs.training, UnavailableDesignProvider)


# --- P: one continuous API workflow -------------------------------------------------------------

def _install(diagnosis, interventions, designs):
    prior = (app.state.diagnostics, app.state.interventions, app.state.designs)
    app.state.diagnostics, app.state.interventions, app.state.designs = diagnosis, interventions, designs
    return prior


def test_case_p_one_continuous_api_workflow_from_human_validation_to_training_generation():
    source, signal, bundle = prepared()
    diagnosis = DiagnosticService(source, ControlledTestReasoner(
        response(bundle, cause_domain="skill_gap", performance_dimension="capability", missing_evidence=[])))
    interventions = InterventionService(
        diagnosis, None,
        ControlledInterventionReasoner(intervention_response(intervention_type="practice_simulation")),
        ControlledSolutionValidator(solution_response()))
    runtime = FakeRuntime()
    designs = DesignService(diagnosis, ValidatedInterventionHandoff(interventions),
                            BedrockTrainingDesigner(client=runtime, diagnostics=diagnosis))
    prior = _install(diagnosis, interventions, designs)
    try:
        client = TestClient(app)
        assert client.get("/diagnostics/mode").json()["design_provider"] == "provider"
        created = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
        assert created.status_code == 201
        # Design before human validation, and before each AWS-4 stage, is refused in order.
        assert client.post("/designs/diagnoses/hyp_1").json()["detail"]["code"] == "diagnosis_not_approved"
        assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "supervisor"}).status_code == 200
        assert client.post("/designs/diagnoses/hyp_1").json()["detail"]["code"] == "intervention_not_proposed"
        proposed = client.post("/interventions/diagnoses/hyp_1/propose")
        assert proposed.status_code == 200 and proposed.json()["handoff"]["training_design_gate"] == "awaiting_solution_validation"
        assert client.post("/designs/diagnoses/hyp_1").json()["detail"]["code"] == "solution_not_validated"
        validated = client.post("/interventions/diagnoses/hyp_1/validate-solution")
        assert validated.status_code == 200 and validated.json()["handoff"]["training_design_gate"] == "permitted"
        assert runtime.calls == []
        designed = client.post("/designs/diagnoses/hyp_1")
        assert designed.status_code == 200, designed.text
        body = designed.json()
        assert body["status"] == "ready_for_alignment_review" and body["generation_mode"] == "provider"
        assert body["intervention"]["intervention_type"] == "practice_simulation"
        assert body["intervention"]["intervention_id"] == validated.json()["proposal"]["intervention_id"]
        assert body["intervention"]["solution_validation_id"] == validated.json()["solution_validation"]["solution_validation_id"]
        basis = body["training_design"]["design_basis"]
        assert basis["intervention"]["validation_source"] == AWS4_VALIDATION_SOURCE
        assert basis["intervention"]["intervention_id"] == body["intervention"]["intervention_id"]
        assert basis["intervention"]["solution_validation_id"] == body["intervention"]["solution_validation_id"]
        assert basis["gap"]["diagnosis_id"] == "hyp_1" and basis["intervention"]["training_design_gate"] == "permitted"
        assert body["alignment_trace"]["assessment"] == "structural_references_only"
        assert body["training_design"]["provider_metadata"]["provider"] == "Amazon Bedrock"
        assert len(runtime.calls) == 1
        assert client.get("/designs/diagnoses/hyp_1").json() == body
        assert client.post("/designs/diagnoses/hyp_1").json() == body and len(runtime.calls) == 1
        # Upstream records are unchanged by the design run.
        assert client.get("/interventions/diagnoses/hyp_1").json() == validated.json()
        assert client.get("/diagnostics/hypotheses/hyp_1").json()["status"] == "approved"
        for leak in ("Person One", "lead", "eval_1", "synthetic.xlsx"):
            assert leak not in json.dumps(runtime.calls[0])
    finally:
        app.state.diagnostics, app.state.interventions, app.state.designs = prior


def test_competition_story_process_problem_and_questioned_solution_never_produce_a_package():
    """Example 2 and Example 3 side by side with Example 1, all through the same service."""
    skill = pipeline("practice_simulation")
    process = pipeline("process_correction", cause="process_gap", revised=True, designer=ForbiddenDesigner())
    questioned = pipeline("training", "partially_aligned", designer=ForbiddenDesigner())
    trained = asyncio.run(skill[2].run("hyp_1"))
    assert trained.training_design is not None and len(skill[3].calls) == 1
    corrected = asyncio.run(process[2].run("hyp_1"))
    assert corrected.status == "alternative_recommended" and corrected.training_design is None
    assert corrected.intervention.intervention_type == "process_correction"
    assert corrected.approved_diagnosis.diagnosis.cause_domain == "process_gap"
    with pytest.raises(DesignError) as error:
        asyncio.run(questioned[2].run("hyp_1"))
    assert error.value.code == "training_design_withheld"


# --- Smoke harness: the same integrated contract, driven with a stub Converse client ------------

def test_training_smoke_harness_exercises_the_integrated_contract_with_a_stub_client(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "training_smoke", Path(__file__).resolve().parents[3] / "scripts" / "run_bedrock_training_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "get_settings", lambda: Settings(bedrock_enabled=True, _env_file=None))
    runtime = FakeRuntime(json.dumps(package()))
    outcomes = asyncio.run(smoke.main(client=runtime))
    assert set(outcomes) == {"Resolution summary clarity", "Required follow-up prompt available in workflow",
                             "Follow-up documented"}
    practice = outcomes["Resolution summary clarity"]
    assert (practice["intervention_type"], practice["alignment_outcome"], practice["training_design_gate"]) == (
        "practice_simulation", "aligned", "permitted")
    assert practice["training_package"] is True and practice["generation_mode"] == "provider"
    assert practice["validation_source"] == AWS4_VALIDATION_SOURCE
    assert practice["intervention_id_matches"] and practice["solution_validation_id_matches"]
    assert practice["training_focus"] == "skill" and practice["practice_turns"] >= 2
    process = outcomes["Required follow-up prompt available in workflow"]
    assert (process["intervention_type"], process["alignment_outcome"], process["training_design_gate"]) == (
        "process_correction", "aligned", "not_applicable")
    assert process["training_package"] is False and process["design_status"] == "alternative_recommended"
    investigate = outcomes["Follow-up documented"]
    assert investigate["intervention_type"] == "investigate_further" and investigate["training_package"] is False
    assert investigate["design_status"] == "evidence_required"
    # Exactly one Converse call: the practice package. No text of any kind is printed as output.
    assert len(runtime.calls) == 1
    sent = json.dumps(runtime.calls[0])
    for leak in ("Synthetic Agent", "Synthetic feedback", "synthetic-demo", "demo_eval_", "demo_hyp_", "int_", "sol_"):
        assert leak not in sent, leak
    # The harness refuses a configured local evaluations path and a disabled Bedrock switch.
    from pathlib import Path as _Path
    monkeypatch.setattr(smoke, "get_settings", lambda: Settings(diagnostic_evaluations_path=_Path("x.jsonl"),
                                                                bedrock_enabled=True, _env_file=None))
    with pytest.raises(SystemExit, match="refuses a configured local evaluations path"):
        asyncio.run(smoke.main(client=runtime))
    monkeypatch.setattr(smoke, "get_settings", lambda: Settings(_env_file=None))
    with pytest.raises(SystemExit, match="COACHLENS_BEDROCK_ENABLED"):
        asyncio.run(smoke.main(client=runtime))
    assert len(runtime.calls) == 1


def test_synthetic_smoke_script_runs_aws5_only_behind_the_live_aws4_gate(monkeypatch):
    """The full live chain harness, driven with stub runtimes: AWS-5 is invoked exactly when
    the AWS-4 review permits it, and reports the withheld outcome otherwise."""
    import importlib.util
    from pathlib import Path
    from app.diagnostics.bedrock import BedrockReasoner
    from app.diagnostics.evidence_validator import BedrockEvidenceValidator
    from app.interventions.bedrock import BedrockInterventionReasoner, BedrockSolutionValidator
    from test_aws3_evidence_validator import validator_response
    from test_bedrock import FakeRuntime as DiagnosticRuntime
    spec = importlib.util.spec_from_file_location(
        "synthetic_smoke", Path(__file__).resolve().parents[3] / "scripts" / "run_bedrock_synthetic_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "get_settings", lambda: Settings(bedrock_enabled=True, _env_file=None))
    calls = {}

    def stub(kind, text):
        runtime = DiagnosticRuntime(text)
        calls[kind] = runtime
        return runtime

    class StubBoundReasoner:
        """Same binding rule as the real class; only the Converse client is a stub."""

        @staticmethod
        def for_synthetic_evaluations(region, model, evaluations, client=None):
            return BedrockReasoner.for_synthetic_evaluations(
                region, model, evaluations, client=stub("diagnosis", DiagnosticRuntime().text))

    for alignment, expect_design in (("aligned", True), ("partially_aligned", False)):
        calls.clear()
        monkeypatch.setattr(smoke, "BedrockReasoner", StubBoundReasoner)
        monkeypatch.setattr(smoke, "BedrockEvidenceValidator",
                            lambda region, model, **kw: BedrockEvidenceValidator(client=stub("evidence", json.dumps(validator_response()))))
        monkeypatch.setattr(smoke, "BedrockInterventionReasoner",
                            lambda region, model, **kw: BedrockInterventionReasoner(client=stub("reasoner", json.dumps(
                                intervention_response(intervention_type="practice_simulation")))))
        monkeypatch.setattr(smoke, "BedrockSolutionValidator",
                            lambda region, model, **kw: BedrockSolutionValidator(client=stub("validator", json.dumps(solution_for(alignment)))))
        monkeypatch.setattr(smoke, "BedrockTrainingDesigner",
                            lambda region, model, **kw: BedrockTrainingDesigner(client=stub("designer", json.dumps(package())), **kw))
        asyncio.run(smoke.main())
        assert len(calls["reasoner"].calls) == 1 and len(calls["validator"].calls) == 1
        assert len(calls["designer"].calls) == (1 if expect_design else 0)
        assert isinstance(calls["diagnosis"], DiagnosticRuntime) and len(calls["diagnosis"].calls) == 1
