"""Real ResultsCX remote diagnosis is structured-only by default. Generated fixtures only."""

import asyncio
from datetime import date
from decimal import Decimal
import inspect
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.diagnostics import bedrock as bedrock_module
from app.diagnostics.bedrock import (ITEM_PAYLOAD_KEYS, SYSTEM_PROMPT, BedrockReasoner,
                                     validate_real_wire_payload)
from app.diagnostics.engine import DiagnosticService, ProviderOutputError, build_bundle, detect_signals
from app.diagnostics import evidence_policy
from app.diagnostics.evidence_policy import (TRANSMIT_REAL_MINIMIZED_TEXT, TextDecision, minimize_text,
                                             prepare_real_evidence)
from app.main import app
from app.results_cx import demo
from app.results_cx.models import CriterionResult, Domain, Evaluation, SourceLineage
from test_bedrock import FakeRuntime, evaluations as synthetic_evaluations, synthetic_reasoner
from test_results_cx_demo import generated_sources


SAFE_COMMENT = "agent did not read the closing disclosure and rushed the caller"


def _trusted(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    return demo.load_results_cx_demo(root)


def _real_service(trusted, runtime=None):
    runtime = runtime or FakeRuntime()
    reasoner = BedrockReasoner.for_trusted_results_cx("us-east-1", "global.anthropic.claude-sonnet-4-6",
                                                      trusted, client=runtime)
    return DiagnosticService(trusted, reasoner), runtime


def test_default_is_structured_only_and_not_configurable():
    assert TRANSMIT_REAL_MINIMIZED_TEXT is False
    assert inspect.signature(prepare_real_evidence).parameters["transmit_minimized_text"].default is False
    # The reasoner's real path calls the preparer without the activation keyword.
    source = inspect.getsource(BedrockReasoner.diagnose)
    assert "prepare_real_evidence(local, evaluations)" in source
    assert "transmit_minimized_text" not in source
    assert not any(word in field for field in Settings.model_fields
                   for word in ("text", "comment", "safe", "minimized", "allow"))


def test_trusted_real_evidence_still_reaches_mocked_bedrock_structured_only(tmp_path):
    trusted = _trusted(tmp_path)
    service, runtime = _real_service(trusted)
    signal = service.list_signals()[0]
    local = service.evidence(signal.signal_id)
    assert signal.feedback_count == 2
    assert all(minimize_text(item.evaluator_feedback, set()).decision == TextDecision.ALLOW_MINIMIZED
               for item in local.items)  # The minimizer alone would admit these generated comments.
    record = asyncio.run(service.diagnose(signal.signal_id))
    assert record.status == "awaiting_review"
    assert record.provider_hypothesis.provider_metadata.generation_mode == "provider"
    (call,) = runtime.calls
    wire = json.loads(call["messages"][0]["content"][0]["text"])
    validate_real_wire_payload(wire)
    assert set(wire["signal"]) and wire["signal"]["failed_criterion_result_count"] == signal.fail_count
    assert wire["signal"]["criterion"] == signal.criterion  # Policy-approved wording still crosses.
    assert all(set(item) == ITEM_PAYLOAD_KEYS for item in wire["evidence_items"])
    assert wire["text_coverage"] == {"total_evidence_items": 2, "evidence_items_with_feedback": 2,
                                     "minimized_text_items_allowed": 0, "text_items_blocked": 2,
                                     "text_items_with_no_text": 0}
    serialized = json.dumps(call)
    payload_text = call["messages"][0]["content"][0]["text"]  # The prompt names the field; the payload must not.
    assert "diagnostic_text" not in payload_text and "minimized_evaluator_feedback" not in payload_text
    for item in local.items:
        assert item.evaluator_feedback and item.evaluator_feedback not in serialized
    # Raw comments remain local and unchanged for the reviewer routes.
    assert service.evidence(signal.signal_id) == local
    assert [item.evaluator_feedback for item in local.items] == ["Synthetic note", "Synthetic note"]
    cited = record.provider_hypothesis.supporting_evidence[0]
    assert (cited.item_id, cited.evaluation_id) == (local.items[0].item_id, local.items[0].evaluation_id)


def test_known_safe_comment_is_withheld_not_blocked_and_not_no_text():
    rows = [Evaluation(internal_id=f"eval_{n}", agent_name=f"Person {n}", qa_name="Reviewer Q",
                       team_leader="Lead L", call_date=date(2026, 1, 1),
                       criteria=[CriterionResult(domain=Domain.COMPLIANCE, question="Closing", answer="No",
                                                 passed=False, max_score=Decimal(5), attained_score=Decimal(0),
                                                 evaluator_feedback=comment,
                                                 lineage=SourceLineage(source_filename="g.xlsx", source_sheet="S",
                                                                       excel_row=n + 1))])
            for n, comment in enumerate([SAFE_COMMENT, "call 555-0100 back", None, "  "], 1)]
    signal = detect_signals(rows)[0]
    bundle = build_bundle(signal, rows)
    assert minimize_text(SAFE_COMMENT, set()).decision == TextDecision.ALLOW_MINIMIZED
    prepared = prepare_real_evidence(bundle, rows)
    assert prepared.text_decisions == {"EVID-001": TextDecision.WITHHELD, "EVID-002": TextDecision.BLOCK,
                                       "EVID-003": TextDecision.NO_TEXT, "EVID-004": TextDecision.NO_TEXT}
    assert prepared.payload["text_coverage"] == {"total_evidence_items": 4, "evidence_items_with_feedback": 3,
                                                 "minimized_text_items_allowed": 0, "text_items_blocked": 2,
                                                 "text_items_with_no_text": 2}
    assert "diagnostic_text" not in json.dumps(prepared.payload)
    assert SAFE_COMMENT not in json.dumps(prepared.payload)
    assert bundle.items[0].evaluator_feedback == SAFE_COMMENT
    for reference, item in zip(prepared.local_references, bundle.items):
        local = prepared.local_references[reference]
        assert (local.item_id, local.evaluation_id, local.source_lineage) == (
            item.item_id, item.evaluation_id, item.source_lineage)
        assert prepared.lookup[reference] == (item.item_id, item.evaluation_id)
    # The same bundle with the deferred argument shows the machinery is intact, not removed.
    activated = prepare_real_evidence(bundle, rows, transmit_minimized_text=True)
    assert activated.text_decisions["EVID-001"] == TextDecision.ALLOW_MINIMIZED
    assert activated.payload["text_coverage"]["minimized_text_items_allowed"] == 1


def test_reasoner_refuses_if_text_ever_appears_in_real_payload(tmp_path, monkeypatch):
    """Even if the preparer were changed to emit text, the reasoner's real path fails closed."""
    trusted = _trusted(tmp_path)
    service, runtime = _real_service(trusted)
    original = evidence_policy.prepare_real_evidence
    monkeypatch.setattr(evidence_policy, "prepare_real_evidence",
                        lambda bundle, rows, **kwargs: original(bundle, rows, transmit_minimized_text=True))
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(service.diagnose(service.list_signals()[0].signal_id))
    assert refused.value.code == "provider_privacy_blocked"
    assert runtime.calls == []


def test_no_request_or_environment_activates_real_text(tmp_path, monkeypatch):
    for name in ("COACHLENS_ALLOW_REAL_TEXT", "COACHLENS_API_ALLOW_REAL_TEXT", "COACHLENS_SEND_COMMENTS",
                 "COACHLENS_BEDROCK_SEND_COMMENTS", "COACHLENS_TRANSMIT_REAL_MINIMIZED_TEXT",
                 "COACHLENS_API_TRANSMIT_REAL_MINIMIZED_TEXT", "COACHLENS_REAL_TEXT", "COACHLENS_MINIMIZED_TEXT"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setattr(demo, "get_settings", lambda: Settings(bedrock_enabled=True, _env_file=None))
    trusted = _trusted(tmp_path)
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        demo.install_results_cx_demo(app, trusted)
        runtime = FakeRuntime()
        app.state.diagnostics.reasoner._client = runtime
        service = app.state.diagnostics
        signal = service.list_signals()[0]
        response = TestClient(app).post(
            f"/diagnostics/signals/{signal.signal_id}/hypotheses?send_comments=true&allow_real_text=true",
            json={"send_comments": True, "allow_real_text": True, "transmit_minimized_text": True,
                  "safe": True, "diagnostic_text": True},
            headers={"x-send-comments": "true", "x-allow-real-text": "true"})
        assert response.status_code == 201
        assert response.json()["status"] == "awaiting_review"
        (call,) = runtime.calls
        payload_text = call["messages"][0]["content"][0]["text"]
        assert "diagnostic_text" not in payload_text and "Synthetic note" not in json.dumps(call)
        wire = json.loads(payload_text)
        assert wire["text_coverage"]["minimized_text_items_allowed"] == 0
        assert wire["text_coverage"]["text_items_blocked"] == signal.feedback_count == 2
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_criterion_policy_unchanged_in_structured_only_mode():
    from test_diagnostics import prepared
    rows, _, _ = prepared()
    for question, expected in (("Agent used the standard greeting", "Agent used the standard greeting"),
                               ("Did agent verify Mrs Johnson identity", "[criterion withheld]"),
                               ("Verify 2 identifiers", "[criterion withheld]")):
        for row in rows:
            row.criteria[0].question = question
        signal = detect_signals(rows)[0]
        wire = prepare_real_evidence(build_bundle(signal, rows), rows).payload
        assert wire["signal"]["criterion"] == expected
        assert all(item["criterion"] == expected and "diagnostic_text" not in item
                   for item in wire["evidence_items"])


def test_prompt_explains_withheld_feedback_without_loosening_schema():
    for fragment in ("may have been withheld", "absence of diagnostic_text never means no local feedback",
                     "Never\ninvent, guess, or paraphrase withheld feedback",
                     "lower provider_reported_confidence or return\nundetermined"):
        assert fragment in SYSTEM_PROMPT
    assert SYSTEM_PROMPT == bedrock_module.REASONING_PROMPT + "\n\n" + bedrock_module.response_contract()
    assert set(bedrock_module.BedrockResponse.model_fields) == {
        "observed_behavioral_defect", "cause_domain", "performance_dimension", "explanation",
        "supporting_evidence_ids", "conflicting_evidence_ids", "missing_evidence",
        "provider_reported_confidence"}


def test_synthetic_aws1_path_unchanged():
    rows = synthetic_evaluations()
    runtime = FakeRuntime()
    service = DiagnosticService(rows, synthetic_reasoner(rows, runtime))
    record = asyncio.run(service.diagnose(service.list_signals()[0].signal_id))
    assert record.status == "awaiting_review"
    (call,) = runtime.calls
    wire = json.loads(call["messages"][0]["content"][0]["text"])
    assert set(wire) == {"signal", "evidence_items"}  # AWS-1 contract: no text, no text_coverage.
    assert all(set(item) == ITEM_PAYLOAD_KEYS for item in wire["evidence_items"])
    assert "missed greeting" not in json.dumps(call)
