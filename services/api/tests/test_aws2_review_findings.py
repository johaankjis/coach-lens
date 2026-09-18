"""AWS-2 review regression tests. Every identifier here is a generated canary, never real data."""

import asyncio
import copy
from datetime import date
from decimal import Decimal
import json
import pickle

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.diagnostics.bedrock import (SYSTEM_PROMPT, BedrockReasoner, provider_safe_payload,
                                     validate_real_wire_payload)
from app.diagnostics.engine import DiagnosticService, ProviderOutputError, build_bundle, detect_signals
from app.diagnostics.evidence_policy import (TextDecision, identity_parts, minimize_text,
                                             population_digest, prepare_real_evidence)
from app.main import app
from app.results_cx import demo
from app.results_cx.models import CriterionResult, Domain, Evaluation, SourceLineage
from test_bedrock import FakeRuntime
from test_results_cx_demo import generated_sources


KNOWN = {"Alice Canaryson", "Bob Reviewerton", "Carol Leadwell", "Ted Short", "\u00c9lodie Accent",
         "Mary-Jo O'Brien"}


@pytest.mark.parametrize("text", [
    # Known identity variants that the original policy let through (H1).
    "AliceCanaryson rushed", "Al\u200bice Canaryson missed it", "\u0410lice Canaryson missed it", "text\u0085more",
    "good call \U0001F600",
    # Unknown third parties, honorifics, places, dates, references (H2).
    "Told Mrs Johnson her insulin claim was denied", "told mrs johnson the claim was denied",
    "Referred to Dr Patel", "Sent to Mercy General Hospital", "Lives on Maple Street",
    "Member born in March", "callback for Jordan tomorrow", "AGENT DID NOT VERIFY MEMBER JOHNSON",
    "see www.example.org", "open the file notes.txt", "ZIP 90210", "call 555-123-4567",
    "id \uff11\uff12\uff13", "member@example.org", "path C:\\notes", "[redacted] said it is fine",
    "line one\nline two", "note: Springfield office", "the caller (Johnson) hung up",
    "A" * 1001,
])
def test_generated_canaries_block(text):
    assert minimize_text(text, KNOWN) == minimize_text(text, KNOWN)
    assert minimize_text(text, KNOWN).decision == TextDecision.BLOCK


@pytest.mark.parametrize(("text", "expected"), [
    ("Alice was rude to the member", "[redacted] was rude to the member"),
    ("Canaryson did not verify", "[redacted] did not verify"),
    ("ALICE CANARYSON'S tone", "[redacted]'S tone"),
    ("Alice\u00a0Canaryson tone", "[redacted] tone"),
    ("Alice-Canaryson tone was poor", "[redacted]-[redacted] tone was poor"),
    ("E\u0301lodie Accent missed it", "[redacted] missed it"),
    ("Mary-Jo asked Brien to retry", "[redacted]-[redacted] asked [redacted] to retry"),
    ("Ted said the agent rushed the caller", "[redacted] said the agent rushed the caller"),
    ("Agent did not verify DOB with the Member. Caller was upset.",
     "Agent did not verify DOB with the Member. Caller was upset."),
    ("I heard the agent skip the closing", "I heard the agent skip the closing"),
    ("agent did not read the closing disclosure and rushed the caller",
     "agent did not read the closing disclosure and rushed the caller"),
])
def test_permitted_text_is_minimized_deterministically(text, expected):
    result = minimize_text(text, KNOWN)
    assert (result.decision, result.text) == (TextDecision.ALLOW_MINIMIZED, expected)
    assert "Alice" not in result.text and "Canaryson" not in result.text and "Ted " not in result.text


def test_identity_parts_cover_every_name_part():
    assert identity_parts({"Mary-Jo O'Brien", "J Smith"}) == {"mary", "jo", "brien", "smith"}


def test_criterion_cannot_bypass_text_policy():
    rows, _, bundle = _rows()
    for question in ("Did agent verify Mrs Johnson identity", "Verify 2 identifiers",
                     "Person One greeting", "Greeting for Springfield members", "Greeting@intake"):
        for row in rows:
            row.criteria[0].question = question
        signal = detect_signals(rows)[0]
        wire = prepare_real_evidence(build_bundle(signal, rows), rows).payload
        assert wire["signal"]["criterion"] == "[criterion withheld]"
        assert all(item["criterion"] == "[criterion withheld]" for item in wire["evidence_items"])
        assert "Johnson" not in json.dumps(wire) and "Springfield" not in json.dumps(wire)
    for row in rows:
        row.criteria[0].question = "Agent used the standard greeting"
    signal = detect_signals(rows)[0]
    wire = prepare_real_evidence(build_bundle(signal, rows), rows).payload
    assert wire["signal"]["criterion"] == "Agent used the standard greeting"


def test_coverage_counts_are_exact_and_prompt_is_not_inflated():
    """14 failed rows: 3 allowed, 9 blocked, 2 without any comment."""
    comments = (["agent skipped the closing summary"] * 3 + ["call 555-0100 back"] * 9 + [None] * 2)
    rows = [Evaluation(internal_id=f"eval_{n}", agent_name=f"Person {n}", qa_name="Reviewer Q",
                       team_leader="Lead L", call_date=date(2026, 1, 1),
                       criteria=[CriterionResult(domain=Domain.COMPLIANCE, question="Closing", answer="No",
                                                 passed=False, max_score=Decimal(5), attained_score=Decimal(0),
                                                 evaluator_feedback=comment,
                                                 lineage=SourceLineage(source_filename="g.xlsx", source_sheet="S",
                                                                       excel_row=n + 1))])
            for n, comment in enumerate(comments, 1)]
    signal = detect_signals(rows)[0]
    # Deferred machinery, exercised explicitly; the reasoner never passes this argument.
    prepared = prepare_real_evidence(build_bundle(signal, rows), rows, transmit_minimized_text=True)
    wire = prepared.payload
    validate_real_wire_payload(wire)
    assert wire["text_coverage"] == {"total_evidence_items": 14, "evidence_items_with_feedback": 12,
                                     "minimized_text_items_allowed": 3, "text_items_blocked": 9,
                                     "text_items_with_no_text": 2}
    assert sum("diagnostic_text" in item for item in wire["evidence_items"]) == 3
    assert list(prepared.text_decisions.values()).count(TextDecision.BLOCK) == 9
    assert "555" not in json.dumps(wire)
    for reference, item in zip(prepared.local_references, build_bundle(signal, rows).items):
        assert prepared.local_references[reference].item_id == item.item_id
        assert prepared.local_references[reference].source_lineage == item.source_lineage
    # The system prompt tells the model what a marker means and never carries evidence.
    assert "[redacted]" in SYSTEM_PROMPT and "text_coverage" in SYSTEM_PROMPT
    assert "555" not in SYSTEM_PROMPT and "eval_" not in SYSTEM_PROMPT


def test_wire_validator_bounds_criterion_and_domain():
    rows, _, bundle = _rows()
    for mutate in (lambda w: w["signal"].__setitem__("criterion", "x" * 1001),
                   lambda w: w["signal"].__setitem__("domain", "raw_workbook"),
                   lambda w: w["evidence_items"][0].__setitem__("domain", "member_experience"),
                   lambda w: w["evidence_items"][0].__setitem__("criterion", "other wording")):
        wire = prepare_real_evidence(bundle, rows).payload
        mutate(wire)
        with pytest.raises(ProviderOutputError, match="projection drifted"):
            validate_real_wire_payload(wire)


def test_trusted_container_cannot_be_forged_copied_or_refilled(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    jsonl = [Evaluation.model_validate_json(e.model_dump_json()) for e in trusted]
    assert jsonl[0] == trusted[0]  # Equal by value, yet never trusted by type.
    for attempt in (lambda: copy.copy(trusted), lambda: copy.deepcopy(trusted),
                    lambda: pickle.dumps(trusted), lambda: trusted.append(jsonl[0]),
                    lambda: trusted.extend(jsonl), lambda: trusted.clear(),
                    lambda: trusted.__setitem__(0, jsonl[0]), lambda: trusted.pop(),
                    lambda: trusted.__iadd__(jsonl), lambda: trusted.sort(key=id)):
        with pytest.raises(TypeError):
            attempt()
    assert len(trusted) == 2

    class Forged(demo.TrustedResultsCXEvaluations):
        def __init__(self, rows):
            list.__init__(self, rows)

    hollow = demo.TrustedResultsCXEvaluations.__new__(demo.TrustedResultsCXEvaluations)
    list.__init__(hollow, jsonl)
    for candidate in (jsonl, list(trusted), trusted[:], tuple(trusted), Forged(jsonl), hollow):
        with pytest.raises(ValueError):
            BedrockReasoner.for_trusted_results_cx("us-east-1", "m", candidate)
    with pytest.raises(ValueError):
        demo.TrustedResultsCXEvaluations(jsonl, _loader_token=object())
    # In-place mutation of a record inside the trusted container is detected before binding.
    trusted[0].criteria[0].evaluator_feedback = "changed after loading"
    with pytest.raises(ValueError, match="changed after loading"):
        BedrockReasoner.for_trusted_results_cx("us-east-1", "m", trusted)


def test_install_refuses_forged_subclass_even_with_bedrock_enabled(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)

    class Forged(demo.TrustedResultsCXEvaluations):
        def __init__(self, rows):
            list.__init__(self, rows)

    monkeypatch.setattr(demo, "get_settings", lambda: Settings(bedrock_enabled=True, _env_file=None))
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        demo.install_results_cx_demo(app, Forged(list(trusted)))
        assert app.state.diagnostics.reasoner.remote_invocation_policy == "privacy_blocked"
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_mutation_after_binding_cannot_change_transmitted_content(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    runtime = FakeRuntime()
    reasoner = BedrockReasoner.for_trusted_results_cx("us-east-1", "m", trusted, client=runtime)
    service = DiagnosticService(trusted, reasoner)
    signal = service.list_signals()[0]
    # Same IDs, new content, on the objects the service and the loader share.
    for evaluation in service.evaluations:
        for criterion in evaluation.criteria:
            if criterion.question.strip() == signal.criterion:
                criterion.evaluator_feedback = "canary injected after binding"
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(service.diagnose(signal.signal_id))
    assert refused.value.code == "provider_privacy_blocked"
    assert runtime.calls == []
    # In-place mutation of the reasoner's private copy is caught by the digest, not just equality.
    reasoner._trusted_evaluations[0].agent_name = "Renamed Person"
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(reasoner.diagnose(service.provider_evidence(signal.signal_id)))
    assert refused.value.code == "provider_privacy_blocked"
    assert runtime.calls == []


def test_population_digest_sees_content_not_only_ids():
    rows = _rows()[0]
    before = population_digest(rows)
    rows[0].criteria[0].lineage.excel_row += 100
    assert population_digest(rows) != before
    rows[0].criteria[0].lineage.excel_row -= 100
    assert population_digest(rows) == before
    rows[0].criteria[0].evaluator_feedback = "same id different text"
    assert population_digest(rows) != before


def test_environment_and_request_cannot_assert_safety(tmp_path, monkeypatch):
    for name in ("COACHLENS_REAL_DATA_SAFE", "COACHLENS_PROVIDER_SAFE", "COACHLENS_MINIMIZED",
                 "COACHLENS_TRUSTED", "COACHLENS_ALLOW_REAL_BEDROCK", "COACHLENS_SYNTHETIC",
                 "COACHLENS_API_TRUSTED", "COACHLENS_API_REAL_MINIMIZED", "COACHLENS_API_PROVIDER_SAFE",
                 "COACHLENS_BEDROCK_TRUSTED", "COACHLENS_BEDROCK_REAL_MINIMIZED"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("COACHLENS_BEDROCK_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.model_extra is None
    assert not any(word in field for field in Settings.model_fields
                   for word in ("safe", "trusted", "minimized", "real", "synthetic"))
    records = tmp_path / "evaluations.jsonl"
    rows = _rows()[0]
    records.write_text("".join(e.model_dump_json() + "\n" for e in rows))
    monkeypatch.setattr(demo, "get_settings", lambda: settings)
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        # JSONL-shaped records through the demo installer, with every knob set, stay blocked.
        loaded = [Evaluation.model_validate_json(line) for line in records.read_text().splitlines()]
        demo.install_results_cx_demo(app, loaded)
        assert app.state.diagnostics.reasoner.remote_invocation_policy == "privacy_blocked"
        runtime = FakeRuntime()
        app.state.diagnostics.reasoner._client = runtime
        signal_id = app.state.diagnostics.list_signals()[0].signal_id
        client = TestClient(app)
        response = client.post(f"/diagnostics/signals/{signal_id}/hypotheses?safe=true&trusted=true",
                               json={"safe": True, "trusted": True, "minimized": True, "provider_safe": True,
                                     "provenance": {"loader": "workbook", "token": "x"}},
                               headers={"x-provider-safe": "true", "x-trusted": "true",
                                        "content-type": "application/json"})
        assert response.status_code == 502
        assert response.json()["detail"] == {"code": "provider_privacy_blocked",
                                             "message": "Remote diagnosis privacy policy blocked"}
        assert runtime.calls == []
        assert client.get("/diagnostics/mode").json()["remote_diagnosis"] == "privacy_blocked"
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_real_path_wire_never_carries_prohibited_data(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    runtime = FakeRuntime()
    reasoner = BedrockReasoner.for_trusted_results_cx("us-east-1", "global.anthropic.claude-sonnet-4-6",
                                                      trusted, client=runtime)
    service = DiagnosticService(trusted, reasoner)
    signal = service.list_signals()[0]
    local = service.evidence(signal.signal_id)
    record = asyncio.run(service.diagnose(signal.signal_id))
    assert record.status == "awaiting_review"
    assert record.provider_hypothesis.provider_metadata.generation_mode == "provider"
    assert record.provider_hypothesis.provider_metadata.invocation_region == "us-east-1"
    assert record.provider_hypothesis.provider_metadata.model == "global.anthropic.claude-sonnet-4-6"
    assert service.evidence(signal.signal_id) == local
    (call,) = runtime.calls
    assert set(call) == {"modelId", "system", "messages", "inferenceConfig"}
    assert call["inferenceConfig"] == {"maxTokens": 1200, "temperature": 0}
    assert call["system"] == [{"text": SYSTEM_PROMPT}]
    assert len(call["messages"]) == 1 and len(call["messages"][0]["content"]) == 1
    wire = json.loads(call["messages"][0]["content"][0]["text"])
    validate_real_wire_payload(wire)
    serialized = json.dumps(call)
    prohibited = {e.agent_name for e in trusted} | {e.qa_name for e in trusted} | {e.team_leader for e in trusted}
    prohibited |= {e.internal_id for e in trusted} | {item.item_id for item in local.items}
    prohibited |= {signal.signal_id, "rcx1_", "ev_", "sig_"}
    prohibited |= {item.source_lineage.source_filename for item in local.items} | {"Export", ".xlsx", str(root)}
    prohibited |= {"source_lineage", "excel_row", '"evaluator_feedback"', '"answer"', "internal_id",
                   "affected_evaluation_ids", "agent_name", "qa_name", "team_leader", "source_sheet"}
    for value in prohibited:
        assert value not in serialized, value
    # Every wire reference maps to exactly one local item, in order, and back to lineage.
    cited = record.provider_hypothesis.supporting_evidence[0]
    assert (cited.item_id, cited.evaluation_id) == (local.items[0].item_id, local.items[0].evaluation_id)


def test_provider_errors_and_malformed_output_store_nothing_and_leak_nothing(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    cases = ((FakeRuntime(text='{"observed_behavioral_defect": "x"}'), "invalid_provider_output"),
             (FakeRuntime(text=json.dumps({"observed_behavioral_defect": "d", "cause_domain": "skill_gap",
                                           "performance_dimension": "execution", "explanation": "e",
                                           "supporting_evidence_ids": ["EVID-001", "EVID-001"],
                                           "conflicting_evidence_ids": [], "missing_evidence": [],
                                           "provider_reported_confidence": 0.5})), "invalid_evidence_reference"),
             (FakeRuntime(stop_reason="max_tokens"), "invalid_provider_output"),
             (FakeRuntime(error=RuntimeError("secret provider detail " + trusted[0].agent_name)), "reasoner_failure"))
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        for runtime, code in cases:
            reasoner = BedrockReasoner.for_trusted_results_cx("us-east-1", "m", trusted, client=runtime)
            app.state.diagnostics = DiagnosticService(trusted, reasoner)
            signal_id = app.state.diagnostics.list_signals()[0].signal_id
            response = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
            assert response.status_code == 502
            assert response.json()["detail"]["code"] == code
            assert trusted[0].agent_name not in response.text and "secret" not in response.text
            assert "Export" not in response.text and "rcx1_" not in response.text
            assert app.state.diagnostics.list_hypotheses(signal_id) == []
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_synthetic_path_and_local_provider_view_unchanged():
    rows, signal, bundle = _rows()
    rows[0].criteria[0].evaluator_feedback = "Person One told Mrs Johnson to call 555-0100"
    signal = detect_signals(rows)[0]
    local = build_bundle(signal, rows)
    # AWS-1 synthetic projection still carries no text at all.
    payload, _ = provider_safe_payload(local.provider_view({"Person One"}))
    assert "diagnostic_text" not in json.dumps(payload) and "Johnson" not in json.dumps(payload)
    # Local raw evidence keeps the original comment for the reviewer.
    assert local.items[0].evaluator_feedback == "Person One told Mrs Johnson to call 555-0100"


def _rows():
    from test_diagnostics import prepared
    return prepared()
