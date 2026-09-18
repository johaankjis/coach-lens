"""AWS-2 boundary tests use generated workbook fixtures, never supplied ResultsCX data."""

import asyncio
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.diagnostics.bedrock import (ITEM_PAYLOAD_KEYS, SIGNAL_PAYLOAD_KEYS, TEXT_COVERAGE_KEYS,
                                     BedrockReasoner, parse_response, validate_real_wire_payload)
from app.diagnostics.engine import DiagnosticService, ProviderOutputError
from app.diagnostics.evidence_policy import TextDecision, minimize_text, prepare_real_evidence
from app.main import app
from app.results_cx import demo
from test_bedrock import FakeRuntime, response
from test_diagnostics import prepared
from test_results_cx_demo import generated_sources


@pytest.mark.parametrize(("text", "decision", "fragment"), [
    (None, TextDecision.NO_TEXT, None), ("  \t ", TextDecision.NO_TEXT, None),
    ("Alice missed the check", TextDecision.ALLOW_MINIMIZED, "[redacted] missed"),
    ("ALICE, then Alice missed it", TextDecision.ALLOW_MINIMIZED, "[redacted], then [redacted]"),
    ("Élodie: explained it", TextDecision.ALLOW_MINIMIZED, "[redacted]: explained"),
    ("Alice2 missed it", TextDecision.BLOCK, None),
    ("alice@example.org was called", TextDecision.BLOCK, None),
    ("Phone 555-123-4567", TextDecision.BLOCK, None),
    ("ID 12345", TextDecision.BLOCK, None),
    ("A" * 1001, TextDecision.BLOCK, None),
    ("Alice; Élodie", TextDecision.BLOCK, None),
])
def test_deterministic_text_decisions(text, decision, fragment):
    result = minimize_text(text, {"Alice", "Élodie"})
    assert result.decision == decision
    if fragment:
        assert fragment in result.text
    else:
        assert result.text is None


def test_local_preparation_preserves_raw_and_maps_exact_lineage():
    rows, signal, bundle = prepared()
    rows[0].criteria[0].evaluator_feedback = "Person One and Reviewer One asked Lead One to retry"
    rows[1].criteria[0].evaluator_feedback = "member@example.org"
    service = DiagnosticService(rows, BedrockReasoner())
    signal = service.list_signals()[0]
    raw = service.evidence(signal.signal_id)
    before = [item.model_dump() for item in raw.items]
    # Exercises the deferred text machinery explicitly; the reasoner never passes this.
    prepared_bundle = prepare_real_evidence(raw, rows, transmit_minimized_text=True)
    wire = prepared_bundle.payload
    serialized = json.dumps(wire)
    assert set(wire) == {"signal", "evidence_items", "text_coverage"}
    assert set(wire["signal"]) == SIGNAL_PAYLOAD_KEYS
    assert set(wire["text_coverage"]) == TEXT_COVERAGE_KEYS
    assert set(wire["evidence_items"][0]) == ITEM_PAYLOAD_KEYS | {"diagnostic_text"}
    assert wire["evidence_items"][0]["diagnostic_text"]["kind"] == "minimized_evaluator_feedback"
    assert wire["text_coverage"] == {"total_evidence_items": 2, "evidence_items_with_feedback": 2,
                                     "minimized_text_items_allowed": 1, "text_items_blocked": 1,
                                     "text_items_with_no_text": 0}
    assert "diagnostic_text" not in wire["evidence_items"][1]
    assert prepared_bundle.text_decisions == {"EVID-001": TextDecision.ALLOW_MINIMIZED,
                                               "EVID-002": TextDecision.BLOCK}
    for reference, item in zip(("EVID-001", "EVID-002"), raw.items):
        local = prepared_bundle.local_references[reference]
        assert (local.item_id, local.evaluation_id, local.source_lineage) == (
            item.item_id, item.evaluation_id, item.source_lineage)
        assert prepared_bundle.lookup[reference] == (item.item_id, item.evaluation_id)
    assert [item.model_dump() for item in service.evidence(signal.signal_id).items] == before
    for forbidden in ("Person One", "Reviewer One", "Lead One", "member@example.org", "eval_1",
                      "ev_", "sig_", "synthetic.xlsx", "Sheet", "source_lineage", '"evaluator_feedback":',
                      "internal_id", "qa_name", "agent_name", "team_leader"):
        assert forbidden not in serialized
    assert wire["signal"]["failed_criterion_result_count"] == signal.fail_count
    assert wire["signal"]["failure_rate"] == str(signal.fail_rate)
    assert wire["signal"]["feedback_count"] == signal.feedback_count


def test_no_text_is_distinct_from_blocked_feedback():
    rows, _, _ = prepared()
    rows[0].criteria[0].evaluator_feedback = "  "
    rows[1].criteria[0].evaluator_feedback = "Phone 123"
    service = DiagnosticService(rows, BedrockReasoner())
    signal = service.list_signals()[0]
    wire = prepare_real_evidence(service.evidence(signal.signal_id), rows).payload
    assert wire["text_coverage"] == {"total_evidence_items": 2, "evidence_items_with_feedback": 2,
                                     "minimized_text_items_allowed": 0, "text_items_blocked": 1,
                                     "text_items_with_no_text": 1}
    assert all("diagnostic_text" not in item for item in wire["evidence_items"])
    assert len(wire["evidence_items"]) == 2


def test_wire_allowlist_refuses_arbitrary_raw_objects():
    rows, _, bundle = prepared()
    with pytest.raises((AttributeError, TypeError)):
        prepare_real_evidence(rows[0], rows)
    projection = prepare_real_evidence(bundle, rows).payload
    projection["raw_evaluation"] = rows[0]
    with pytest.raises(ProviderOutputError, match="projection drifted"):
        validate_real_wire_payload(projection)
    projection = prepare_real_evidence(bundle, rows).payload
    projection["evidence_items"][0]["criterion"] = rows[0]
    with pytest.raises(ProviderOutputError, match="projection drifted"):
        validate_real_wire_payload(projection)
    projection = prepare_real_evidence(bundle, rows).payload
    projection["text_coverage"]["text_items_blocked"] += 1
    with pytest.raises(ProviderOutputError, match="projection drifted"):
        validate_real_wire_payload(projection)


def test_real_loader_gate_and_mocked_provider(tmp_path, monkeypatch):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    with pytest.raises(ValueError):
        BedrockReasoner.for_trusted_results_cx("us-east-1", "m", list(trusted))
    monkeypatch.setenv("COACHLENS_REAL_SAFE", "true")
    assert "real_safe" not in Settings.model_fields
    runtime = FakeRuntime()
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        monkeypatch.setattr(demo, "get_settings", lambda: Settings(bedrock_enabled=True, _env_file=None))
        demo.install_results_cx_demo(app, trusted)
        reasoner = app.state.diagnostics.reasoner
        assert reasoner.remote_invocation_policy == "real_minimized"
        reasoner._client = runtime
        svc = app.state.diagnostics
        signal = svc.list_signals()[0]
        before = svc.evidence(signal.signal_id).model_dump()
        result = TestClient(app).post(f"/diagnostics/signals/{signal.signal_id}/hypotheses",
                                      json={"safe": True, "synthetic": False},
                                      headers={"x-evidence-safe": "true"})
        assert result.status_code == 201
        record = result.json()
        assert record["status"] == "awaiting_review"
        assert record["provider_hypothesis"]["provider_metadata"]["generation_mode"] == "provider"
        assert svc.evidence(signal.signal_id).model_dump() == before
        assert len(runtime.calls) == 1
        wire = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])
        validate_real_wire_payload(wire)
        assert wire["text_coverage"]["total_evidence_items"] == signal.evaluated_results
        assert wire["text_coverage"]["evidence_items_with_feedback"] == signal.feedback_count
        assert record["provider_hypothesis"]["supporting_evidence"][0]["item_id"] == before["items"][0]["item_id"]
        for value in (trusted[0].agent_name, trusted[0].qa_name, trusted[0].team_leader,
                      trusted[0].internal_id, before["items"][0]["item_id"],
                      before["items"][0]["source_lineage"]["source_filename"], "Export"):
            assert value not in json.dumps(runtime.calls[0])
        # The same records without loader provenance remain blocked, regardless of env or request.
        demo.install_results_cx_demo(app, list(trusted))
        app.state.diagnostics.reasoner._client = FakeRuntime()
        refused = TestClient(app).post(f"/diagnostics/signals/{signal.signal_id}/hypotheses",
                                       json={"safe": True})
        assert refused.status_code == 502
        assert refused.json()["detail"]["code"] == "provider_privacy_blocked"
        assert app.state.diagnostics.reasoner._client.calls == []
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_real_provider_malformed_and_failure_store_nothing(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    for runtime, code in ((FakeRuntime(text="not-json"), "invalid_provider_output"),
                          (FakeRuntime(error=RuntimeError("private provider detail")), "reasoner_failure")):
        svc = DiagnosticService(trusted, BedrockReasoner.for_trusted_results_cx(
            "us-east-1", "global.anthropic.claude-sonnet-4-6", trusted, client=runtime))
        signal_id = svc.list_signals()[0].signal_id
        with pytest.raises(ProviderOutputError) as refused:
            asyncio.run(svc.diagnose(signal_id))
        assert refused.value.code == code
        assert len(runtime.calls) == 1
        assert svc.list_hypotheses(signal_id) == []


def test_trusted_binding_refuses_changed_provider_view(tmp_path):
    root = tmp_path / "raw"
    generated_sources(root)
    trusted = demo.load_results_cx_demo(root)
    runtime = FakeRuntime()
    reasoner = BedrockReasoner.for_trusted_results_cx("us-east-1", "m", trusted, client=runtime)
    service = DiagnosticService(trusted, reasoner)
    signal_id = service.list_signals()[0].signal_id
    forged = service.provider_evidence(signal_id).model_copy(deep=True)
    forged.items[0].attained_score += 1
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(reasoner.diagnose(forged))
    assert refused.value.code == "provider_privacy_blocked"
    assert runtime.calls == []


def test_cross_signal_and_invented_references_refused():
    lookup = {"SIGNAL-001": ("signal", None), "EVID-001": ("local", "evaluation")}
    for cited in ("EVID-999", "EVID-002", "local", "EVID-001 "):
        with pytest.raises(ProviderOutputError) as refused:
            parse_response(response(supporting_evidence_ids=[cited]), lookup)
        assert refused.value.code == "invalid_evidence_reference"
