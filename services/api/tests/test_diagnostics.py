"""Synthetic-only M3 diagnostic contract tests. No real ResultsCX values appear here."""

from datetime import date
from decimal import Decimal
import asyncio
import threading
import time

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.diagnostics.engine import (ControlledTestReasoner, DiagnosticError,
                                    DiagnosticService, ProviderOutputError, build_bundle,
                                    detect_signals, validate_provider_output)
from app.diagnostics.models import (CauseDomain, DiagnosticHypothesis, EvidenceReference,
                                    HumanRevision, PerformanceDimension, ProviderMetadata,
                                    redact_known_identities)
from app.main import app
from app.results_cx.models import CriterionResult, Domain, Evaluation, SourceLineage


def criterion(question, passed, row, feedback=None, domain=Domain.COMPLIANCE,
              max_score=Decimal(10), attained=None):
    return CriterionResult(domain=domain, question=question,
                           answer="Yes" if passed else "No", passed=passed,
                           max_score=max_score,
                           attained_score=attained if attained is not None else (max_score if passed else Decimal(2)),
                           evaluator_feedback=feedback,
                           lineage=SourceLineage(source_filename="synthetic.xlsx",
                                                 source_sheet="Sheet", excel_row=row))


def evaluations():
    return [
        Evaluation(internal_id="eval_1", agent_name="Person One", qa_name="Reviewer One",
                   team_leader="Lead One", call_date=date(2026, 1, 1),
                   criteria=[criterion("Greeting", False, 2, "Person One missed greeting"),
                             criterion("Closure", True, 3)]),
        Evaluation(internal_id="eval_2", agent_name="Person Two", qa_name="Reviewer Two",
                   team_leader="Lead Two", call_date=date(2026, 1, 2),
                   criteria=[criterion("Greeting", False, 4), criterion("Closure", True, 5)]),
    ]


def prepared():
    source = evaluations()
    signal = detect_signals(source)[0]
    return source, signal, build_bundle(signal, source)


def ref(bundle, index):
    item = bundle.items[index]
    return {"item_id": item.item_id, "evaluation_id": item.evaluation_id}


def response(bundle, **changes):
    raw = {"hypothesis_id": "hyp_1", "signal_id": bundle.signal.signal_id,
           "observed_behavioral_defect": "Greeting criterion failed in two evaluations",
           "cause_domain": "undetermined", "performance_dimension": "undetermined",
           "explanation": "Available facts establish failures but do not establish why.",
           "supporting_evidence": [ref(bundle, 0)],
           "conflicting_evidence": [], "missing_evidence": ["Ask reviewer for context"],
           "provider_reported_confidence": "0.2",
           "provider_metadata": {"provider": "controlled-test"}}
    return raw | changes


def service(source, bundle, **changes):
    return DiagnosticService(source, ControlledTestReasoner(response(bundle, **changes)))


def diagnosed():
    source, signal, bundle = prepared()
    svc = service(source, bundle)
    asyncio.run(svc.diagnose(signal.signal_id))
    return svc, bundle


def revision(bundle, **changes):
    fields = dict(observed_behavioral_defect="Two failed greeting checks", cause_domain="process_gap",
                  performance_dimension="undetermined", explanation="Human reviewer found a process issue.",
                  supporting_evidence=[EvidenceReference(**ref(bundle, 1))],
                  conflicting_evidence=[], missing_evidence=[])
    return HumanRevision(**(fields | changes))


# --- Signals (FACT layer) -------------------------------------------------------------

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


def test_signals_have_no_causal_fields_and_match_m2_statistics():
    from app.results_cx.pipeline import analyze
    source = evaluations()
    by_key = {(s.domain, s.question): s for s in analyze(source) if s.question}
    for signal in detect_signals(source):
        stat = by_key[(signal.domain, signal.criterion)]
        assert (signal.pass_count, signal.fail_count, signal.fail_rate, signal.score_rate,
                signal.feedback_count) == (stat.pass_count, stat.fail_count, stat.fail_rate,
                                           stat.score_rate, stat.feedback_count)
        assert not {"cause_domain", "performance_dimension", "confidence"} & set(signal.model_dump())


def test_signal_edge_cases_empty_all_fail_decimal_ties_and_domains():
    assert detect_signals([]) == []
    assert DiagnosticService([], ControlledTestReasoner(None)).list_signals() == []
    source = [Evaluation(internal_id=f"e{i}", agent_name="A", qa_name="Q", team_leader="L",
                         call_date=date(2026, 1, i + 1),
                         criteria=[criterion("Same", False, 2 + i, max_score=Decimal("7.5"), attained=Decimal("1.25")),
                                   criterion("Same", False, 2 + i, domain=Domain.BUSINESS_PROCESS,
                                             max_score=Decimal("7.5"), attained=Decimal("1.25")),
                                   criterion("  Padded  ", True, 2 + i, domain=Domain.MEMBER_EXPERIENCE)])
              for i in range(3)]
    signals = detect_signals(source)
    assert [(s.domain.value, s.criterion, s.fail_count) for s in signals] == [
        ("business_process", "Same", 3), ("compliance", "Same", 3), ("member_experience", "Padded", 0)]
    assert len({s.signal_id for s in signals}) == 3  # Same wording in two domains stays distinct.
    assert signals[0].score_rate == Decimal("1.25") / Decimal("7.5")
    assert signals[0].feedback_count == 0 and signals[0].feedback_coverage == 0
    assert signals[0].fail_rate == 1 and signals[2].fail_rate == 0
    bundle = build_bundle(signals[2], source)
    assert [item.evaluation_id for item in bundle.items] == ["e0", "e1", "e2"]


def test_duplicate_evaluation_ids_are_rejected_at_service_construction():
    source = evaluations()
    with pytest.raises(DiagnosticError) as info:
        DiagnosticService(source + [source[0].model_copy(deep=True)], ControlledTestReasoner(None))
    assert info.value.code == "duplicate_evaluation"


# --- Evidence bundle -------------------------------------------------------------------

def test_evidence_item_ids_are_stable_content_derived_and_unique_across_bundles():
    source, _, bundle = prepared()
    again = build_bundle(detect_signals(list(reversed(source)))[0], source)
    assert [i.item_id for i in bundle.items] == [i.item_id for i in again.items]
    other = build_bundle(detect_signals(source)[1], source)
    assert not {i.item_id for i in bundle.items} & {i.item_id for i in other.items}
    assert "synthetic.xlsx" not in "".join(i.item_id for i in bundle.items)


def test_provider_view_minimizes_identity_and_preserves_reference_lookup():
    source, signal, bundle = prepared()
    svc = service(source, bundle)
    view = svc.provider_evidence(signal.signal_id)
    serialized = view.model_dump_json()
    assert "Person One" not in serialized and "Reviewer One" not in serialized
    assert "synthetic.xlsx" not in serialized and "excel_row" not in serialized
    assert "[redacted] missed greeting" in serialized
    assert view.items[0].item_id == bundle.items[0].item_id
    assert "source_lineages" not in serialized
    assert "agent_name" not in serialized


def test_redaction_is_whole_word_case_insensitive_and_nothing_more():
    terms = {"Al Doe", "Al", "Bo Ray"}
    assert redact_known_identities("al doe; AL DOE; Al  Doe; Al forgot.", terms) == \
        "[redacted]; [redacted]; [redacted]; [redacted] forgot."
    # Short names must not corrupt unrelated words.
    assert redact_known_identities("Also, Alan and Doe remained.", terms) == "Also, Alan and Doe remained."
    # Documented non-guarantees: this is not PII/PHI detection.
    leak = ("member Jane Roe, jane.roe@example.com, 555-123-4567, account ACCT-99887766, "
            "12 Example Street, MRN 0012345, DOB 01/02/1980, reviewer Ray")
    assert redact_known_identities(leak, terms) == leak
    assert redact_known_identities("unchanged", set()) == "unchanged"


def test_bundle_rejects_inconsistent_lineage():
    source, signal, _ = prepared()
    changed = signal.model_copy(deep=True)
    changed.source_lineages[0].excel_row = 999
    with pytest.raises(DiagnosticError) as info:
        build_bundle(changed, source)
    assert info.value.code == "evidence_mismatch"


# --- Provider output is untrusted (HYPOTHESIS layer) -----------------------------------

@pytest.mark.parametrize("change,code", [
    ({"signal_id": "unknown"}, "evidence_mismatch"),
    ({"provider_reported_confidence": "1.01"}, "invalid_provider_output"),
    ({"provider_reported_confidence": "-0.01"}, "invalid_provider_output"),
    ({"provider_reported_confidence": "NaN"}, "invalid_provider_output"),
    ({"provider_reported_confidence": float("inf")}, "invalid_provider_output"),
    ({"provider_reported_confidence": "high"}, "invalid_provider_output"),
    ({"provider_reported_confidence": None}, "invalid_provider_output"),
    ({"provider_reported_confidence": True}, "invalid_provider_output"),
    ({"cause_domain": "will_gap"}, "invalid_provider_output"),
    ({"performance_dimension": "process_or_system"}, "invalid_provider_output"),
    ({"explanation": ""}, "invalid_provider_output"),
    ({"explanation": "x" * 20_001}, "invalid_provider_output"),
    ({"hypothesis_id": "h" * 129}, "invalid_provider_output"),
    ({"missing_evidence": []}, "invalid_provider_output"),
    ({"missing_evidence": ["q"] * 201}, "invalid_provider_output"),
    ({"supporting_evidence": []}, "invalid_provider_output"),
    ({"unexpected": 1}, "invalid_provider_output"),
    ({"supporting_evidence": [{"item_id": "row_1", "evaluation_id": "eval_1"}]}, "invalid_evidence_reference"),
    ({"supporting_evidence": [{"item_id": "signal", "evaluation_id": "eval_1"}]}, "invalid_evidence_reference"),
])
def test_provider_output_is_untrusted(change, code):
    _, _, bundle = prepared()
    with pytest.raises(ProviderOutputError) as info:
        validate_provider_output(response(bundle, **change), bundle)
    assert info.value.code == code


def test_provider_output_missing_confidence_is_rejected():
    _, _, bundle = prepared()
    raw = response(bundle)
    del raw["provider_reported_confidence"]
    with pytest.raises(ProviderOutputError):
        validate_provider_output(raw, bundle)


def test_provider_citations_bind_to_this_bundle():
    source, _, bundle = prepared()
    other = build_bundle(detect_signals(source)[1], source)
    good = ref(bundle, 0)
    cases = [
        [ref(other, 0)],                                                   # evidence from another bundle
        [{"item_id": good["item_id"], "evaluation_id": "eval_2"}],         # right item, wrong evaluation
        [{"item_id": good["item_id"]}],                                    # row citation without evaluation
        [good, good],                                                      # duplicate
        [{"item_id": "ev_" + "0" * 24, "evaluation_id": "eval_1"}],        # fabricated
    ]
    for supporting in cases:
        with pytest.raises(ProviderOutputError) as info:
            validate_provider_output(response(bundle, supporting_evidence=supporting), bundle)
        assert info.value.code == "invalid_evidence_reference"
    with pytest.raises(ProviderOutputError) as info:
        validate_provider_output(response(bundle, conflicting_evidence=[good]), bundle)
    assert info.value.code == "invalid_evidence_reference"
    accepted = validate_provider_output(response(bundle, supporting_evidence=[{"item_id": "signal"}],
                                                 conflicting_evidence=[good]), bundle)
    assert accepted.supporting_evidence[0].evaluation_id is None


@pytest.mark.parametrize("raw", [None, [], 42, "not a mapping", '{"hypothesis_id": "x"}', object()])
def test_provider_non_mapping_output_is_rejected(raw):
    _, _, bundle = prepared()
    with pytest.raises(ProviderOutputError) as info:
        validate_provider_output(raw, bundle)
    assert info.value.code == "invalid_provider_output"


def test_prebuilt_model_instances_cannot_bypass_provider_validation():
    _, _, bundle = prepared()
    forged = DiagnosticHypothesis.model_construct(**(response(bundle) | {
        "cause_domain": "will_gap", "provider_reported_confidence": Decimal("7"),
        "explanation": "", "missing_evidence": [],
        "supporting_evidence": [EvidenceReference(**ref(bundle, 0))], "conflicting_evidence": [],
        "provider_metadata": ProviderMetadata.model_construct(provider="")}))
    with pytest.raises(ProviderOutputError) as info:
        validate_provider_output(forged, bundle)
    assert info.value.code == "invalid_provider_output"

    class Subclass(DiagnosticHypothesis):
        pass
    accepted = validate_provider_output(Subclass.model_validate(response(bundle)), bundle)
    assert type(accepted) is DiagnosticHypothesis


def test_stored_hypothesis_is_isolated_from_provider_object():
    source, signal, bundle = prepared()
    candidate = DiagnosticHypothesis.model_validate(response(bundle))
    svc = DiagnosticService(source, ControlledTestReasoner(candidate))
    record = asyncio.run(svc.diagnose(signal.signal_id))
    assert record.provider_hypothesis == candidate and record.provider_hypothesis is not candidate
    with pytest.raises(ValidationError):
        candidate.explanation = "mutated"  # Frozen value object.


# --- Taxonomy --------------------------------------------------------------------------

def test_taxonomy_keeps_cause_domain_and_skill_will_distinct():
    assert [c.value for c in CauseDomain] == ["knowledge_gap", "skill_gap", "process_gap", "undetermined"]
    assert [d.value for d in PerformanceDimension] == ["capability", "execution", "undetermined"]
    assert not {d.value for d in PerformanceDimension} - {"undetermined"} & {c.value for c in CauseDomain}
    _, _, bundle = prepared()
    with pytest.raises(ValidationError):
        revision(bundle, cause_domain="will_gap")
    with pytest.raises(ValidationError):
        revision(bundle, cause_domain="undetermined", missing_evidence=[])
    assert revision(bundle, cause_domain="undetermined", missing_evidence=["what changed?"]).cause_domain == "undetermined"


# --- Human review (DECISION layer) ----------------------------------------------------

def test_review_and_approval_gate():
    svc, _ = diagnosed()
    record = svc.get("hyp_1")
    assert record.status == "awaiting_review"
    assert "status" not in record.provider_hypothesis.model_dump()  # Lifecycle lives on the record.
    with pytest.raises(DiagnosticError, match="not been approved"):
        svc.get_approved_diagnosis("hyp_1")
    svc.approve("hyp_1", "human_1")
    approved = svc.get_approved_diagnosis("hyp_1")
    assert approved.human_revised is False and approved.approved_by == "human_1"
    assert approved.diagnosis.provider_metadata.provider == "controlled-test"
    with pytest.raises(DiagnosticError) as info:
        svc.reject("hyp_1", "human_1", "reason")
    assert info.value.code == "invalid_state_transition"
    assert svc.get("hyp_1").events[0].occurred_at.tzinfo is not None


@pytest.mark.parametrize("path,attempts", [
    (["approve"], ["approve", "reject", "revise"]),
    (["reject"], ["approve", "reject", "revise"]),
    (["revise"], ["reject", "revise"]),
    (["revise", "approve"], ["approve", "reject", "revise"]),
])
def test_every_illegal_transition_is_refused(path, attempts):
    svc, bundle = diagnosed()
    actions = {"approve": lambda: svc.approve("hyp_1", "h"),
               "reject": lambda: svc.reject("hyp_1", "h", "why"),
               "revise": lambda: svc.revise("hyp_1", "h", revision(bundle), "why")}
    for step in path:
        actions[step]()
    before = svc.get("hyp_1")
    for attempt in attempts:
        with pytest.raises(DiagnosticError) as info:
            actions[attempt]()
        assert info.value.code == "invalid_state_transition"
    assert svc.get("hyp_1") == before  # Refused attempts leave no trace.


def test_reject_and_revision_audit():
    svc, bundle = diagnosed()
    svc.reject("hyp_1", "human_2", "Insufficient context")
    with pytest.raises(DiagnosticError) as info:
        svc.get_approved_diagnosis("hyp_1")
    assert info.value.code == "diagnosis_not_approved"

    svc, bundle = diagnosed()
    original = svc.get("hyp_1").provider_hypothesis.model_dump()
    proposed = revision(bundle)
    record = svc.revise("hyp_1", "human_3", proposed, "Additional context reviewed")
    assert record.status == "revised" and not record.revision_approved
    assert record.provider_hypothesis.model_dump() == original
    with pytest.raises(DiagnosticError):
        svc.get_approved_diagnosis("hyp_1")
    svc.approve("hyp_1", "human_4")
    approved = svc.get_approved_diagnosis("hyp_1")
    assert approved.human_revised and approved.diagnosis == proposed
    assert approved.approved_by == "human_4"
    record = svc.get("hyp_1")
    assert [event.action for event in record.events] == ["revise", "approve"]
    assert record.events[0].revision == proposed
    assert record.events[0].rationale == "Additional context reviewed"
    assert record.events[0].occurred_at <= record.events[1].occurred_at
    assert record.provider_hypothesis.model_dump() == original


def test_revision_references_are_validated_and_bypass_resistant():
    svc, bundle = diagnosed()
    bad = revision(bundle, supporting_evidence=[EvidenceReference(item_id="ev_" + "1" * 24, evaluation_id="eval_1")])
    with pytest.raises(DiagnosticError) as info:
        svc.revise("hyp_1", "human", bad, "reviewed")
    assert info.value.code == "invalid_evidence_reference"
    forged = HumanRevision.model_construct(observed_behavioral_defect="", cause_domain="will_gap",
                                           performance_dimension="x", explanation="",
                                           supporting_evidence=[EvidenceReference(item_id="signal")],
                                           conflicting_evidence=[], missing_evidence=[])
    with pytest.raises(DiagnosticError) as info:
        svc.revise("hyp_1", "human", forged, "reviewed")
    assert info.value.code == "malformed_revision"
    with pytest.raises(DiagnosticError) as info:
        svc.revise("hyp_1", "human", "not a revision", "reviewed")
    assert info.value.code == "malformed_revision"
    with pytest.raises(DiagnosticError) as info:
        svc.revise("hyp_1", "human", revision(bundle), "   ")
    assert info.value.code == "invalid_review"
    assert svc.get("hyp_1").status == "awaiting_review" and svc.get("hyp_1").events == []
    assert svc.revise("hyp_1", "human", revision(bundle).model_dump(), "as plain data").status == "revised"


def test_audit_history_cannot_be_mutated_through_returned_objects():
    svc, bundle = diagnosed()
    snapshot = svc.get("hyp_1")
    snapshot.status = "approved"
    with pytest.raises(DiagnosticError):
        svc.get_approved_diagnosis("hyp_1")
    returned = svc.revise("hyp_1", "human", revision(bundle), "why")
    returned.events.clear()
    returned.human_revision = None
    stored = svc.get("hyp_1")
    assert stored.status == "revised" and len(stored.events) == 1 and stored.human_revision is not None
    with pytest.raises(ValidationError):
        stored.events[0].revision.explanation = "tampered"


def test_concurrent_approvals_produce_exactly_one_decision():
    svc, _ = diagnosed()
    original = svc._event
    def slow_event(*args, **kwargs):
        time.sleep(0.005)
        return original(*args, **kwargs)
    svc._event = slow_event
    outcomes = []
    def attempt():
        try:
            svc.approve("hyp_1", "h")
            outcomes.append("ok")
        except DiagnosticError as exc:
            outcomes.append(exc.code)
    threads = [threading.Thread(target=attempt) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1 and outcomes.count("invalid_state_transition") == 11
    assert [e.action for e in svc.get("hyp_1").events] == ["approve"]


# --- API -------------------------------------------------------------------------------

def test_api_aggregate_safe_and_errors():
    source, signal, bundle = prepared()
    prior = app.state.diagnostics
    app.state.diagnostics = service(source, bundle)
    try:
        with TestClient(app) as client:
            signals = client.get("/diagnostics/signals")
            assert signals.status_code == 200
            assert len(signals.json()) == 2
            assert "Person One" not in signals.text
            evidence = client.get(f"/diagnostics/signals/{signal.signal_id}/evidence")
            assert evidence.status_code == 200
            assert "Person One" not in evidence.text and "synthetic.xlsx" not in evidence.text
            assert "source_lineage" not in evidence.text
            assert client.get("/diagnostics/signals/missing/evidence").status_code == 404
            assert client.get("/diagnostics/hypotheses/missing").status_code == 404
            assert client.post("/diagnostics/signals/missing/hypotheses").status_code == 404
            created = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
            assert created.status_code == 201
            assert "status" not in created.json()["provider_hypothesis"]
            duplicate = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
            assert duplicate.status_code == 502 and duplicate.json()["detail"]["code"] == "invalid_provider_output"
            assert client.get("/diagnostics/hypotheses/hyp_1/approved").status_code == 403
            assert client.post("/diagnostics/hypotheses/hyp_1/reject", json={"reviewer_id": "h", "rationale": ""}).status_code == 422
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "  "}).status_code == 422
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={}).status_code == 422
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", content=b"{", headers={"content-type": "application/json"}).status_code == 422
            bad = client.post("/diagnostics/hypotheses/hyp_1/revise", json={
                "reviewer_id": "h", "rationale": "r", "revision": revision(bundle).model_dump() | {"cause_domain": "will_gap"}})
            assert bad.status_code == 422
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "human"}).status_code == 200
            approved = client.get("/diagnostics/hypotheses/hyp_1/approved")
            assert approved.status_code == 200 and approved.json()["approved_by"] == "human"
            assert client.post("/diagnostics/hypotheses/hyp_1/approve", json={"reviewer_id": "human"}).status_code == 409
            assert client.post("/diagnostics/hypotheses/hyp_1/revise", json={
                "reviewer_id": "h", "rationale": "r", "revision": revision(bundle).model_dump()}).status_code == 409
    finally:
        app.state.diagnostics = prior


def test_api_provider_failures_are_upstream_errors_without_leakage():
    source, signal, bundle = prepared()
    secret = source[0].criteria[0].evaluator_feedback

    class Crashing:
        async def diagnose(self, evidence_bundle):
            raise RuntimeError("internal detail " + secret)

    class Garbage:
        async def diagnose(self, evidence_bundle):
            return {"hypothesis_id": "x", "leak": evidence_bundle.items[0].evaluator_feedback}

    prior = app.state.diagnostics
    try:
        with TestClient(app) as client:
            for reasoner, code in ((Crashing(), "reasoner_failure"), (Garbage(), "invalid_provider_output")):
                app.state.diagnostics = DiagnosticService(source, reasoner)
                result = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
                assert result.status_code == 502
                assert result.json()["detail"]["code"] == code
                assert "missed greeting" not in result.text and "Traceback" not in result.text
                assert client.get("/diagnostics/hypotheses/x").status_code == 404
    finally:
        app.state.diagnostics = prior


def test_api_unavailable_reasoner_returns_structured_error():
    source, signal, _ = prepared()
    prior = app.state.diagnostics
    from app.main import UnavailableReasoner
    app.state.diagnostics = DiagnosticService(source, UnavailableReasoner())
    try:
        with TestClient(app) as client:
            result = client.post(f"/diagnostics/signals/{signal.signal_id}/hypotheses")
            assert result.status_code == 503
            assert result.json()["detail"]["code"] == "reasoner_unavailable"
    finally:
        app.state.diagnostics = prior
