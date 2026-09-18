"""Synthetic-only AWS boundary tests; no network or credentials."""

import asyncio
import json

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.diagnostics.bedrock import BedrockReasoner, parse_response, provider_safe_payload
from app.diagnostics.engine import DiagnosticService, ProviderOutputError, UnavailableReasoner, provider_kind
from app.main import app
from app.results_cx import demo
from test_diagnostics import evaluations


def response(**changes):
    base = {"observed_behavioral_defect": "Synthetic closing check failed",
            "cause_domain": "undetermined", "performance_dimension": "undetermined",
            "explanation": "The structured checks do not distinguish causes.",
            "supporting_evidence_ids": ["EVID-001"], "conflicting_evidence_ids": [],
            "missing_evidence": ["A direct observation of the workflow"],
            "provider_reported_confidence": 0.2}
    return json.dumps(base | changes)


class FakeRuntime:
    def __init__(self, text=None, error=None):
        self.text = response() if text is None else text
        self.error = error
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": self.text}]}},
                "ResponseMetadata": {"RequestId": "synthetic-request-id"}}


def service(client=None, synthetic=True):
    runtime = client or FakeRuntime()
    svc = DiagnosticService(evaluations(), BedrockReasoner(synthetic_evidence=synthetic, client=runtime))
    return svc, runtime, svc.list_signals()[0].signal_id


def test_settings_selection_and_provider_classification(monkeypatch):
    settings = Settings(_env_file=None)
    assert (settings.bedrock_enabled, settings.bedrock_region, settings.bedrock_model_id) == (
        False, "us-east-1", "global.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("COACHLENS_BEDROCK_ENABLED", "true")
    monkeypatch.setenv("COACHLENS_BEDROCK_REGION", "us-west-2")
    monkeypatch.setenv("COACHLENS_BEDROCK_MODEL_ID", "test-profile")
    settings = Settings(_env_file=None)
    assert (settings.bedrock_enabled, settings.bedrock_region, settings.bedrock_model_id) == (
        True, "us-west-2", "test-profile")
    assert provider_kind(BedrockReasoner()) == "provider"
    assert provider_kind(UnavailableReasoner()) == "unavailable"


def test_coverage_and_privacy_projection():
    svc, _, signal_id = service()
    bundle = svc.provider_evidence(signal_id)
    payload, lookup = provider_safe_payload(bundle)
    signal = payload["signal"]
    assert signal["failed_criterion_result_count"] == 2
    assert signal["evaluated_criterion_result_count"] == 2
    assert signal["failure_rate"] == "1"
    assert signal["evaluations_containing_criterion"] == 2
    assert signal["total_loaded_evaluations"] == 2
    assert signal["feedback_count"] == 1
    assert signal["passed_criterion_result_count"] == 0
    assert signal["max_score_total"] == "20"
    assert len(lookup) == 3 and lookup["SIGNAL-001"] == ("signal", None)
    dumped = json.dumps(payload)
    for forbidden in ("Person One", "Reviewer One", "Lead One", "eval_1", "sig_", "ev_",
                      "synthetic.xlsx", "Sheet", "missed greeting", "evaluator_feedback",
                      "source_lineage", "source_lineages", "answer", "agent_name", "qa_name"):
        assert forbidden not in dumped


def test_coverage_incomplete_dataset_is_preserved():
    rows = evaluations()
    rows.append(rows[0].model_copy(update={"internal_id": "eval_3", "criteria": []}))
    svc = DiagnosticService(rows, BedrockReasoner(synthetic_evidence=True, client=FakeRuntime()))
    payload, _ = provider_safe_payload(svc.provider_evidence(svc.list_signals()[0].signal_id))
    assert payload["signal"]["failure_rate"] == "1"
    assert payload["signal"]["evaluations_containing_criterion"] == 2
    assert payload["signal"]["total_loaded_evaluations"] == 3


@pytest.mark.parametrize("bad", [
    "not-json", response(cause_domain="will_gap"), response(provider_reported_confidence=2),
    response(supporting_evidence_ids=["EVID-999"]),
    response(supporting_evidence_ids=["EVID-001", "EVID-001"]),
    response(conflicting_evidence_ids=["EVID-001"]),
    response(explanation=""), response(explanation="   "), response(missing_evidence=[]),
    response(provider_reported_confidence=True),
    response(source_lineage={"source_filename": "forbidden"}),
])
def test_strict_response_rejection(bad):
    svc, _, signal_id = service(FakeRuntime(bad))
    with pytest.raises(ProviderOutputError):
        asyncio.run(svc.diagnose(signal_id))
    assert svc.list_hypotheses(signal_id) == []


def test_bedrock_converse_validates_and_records_provenance():
    svc, runtime, signal_id = service()
    record = asyncio.run(svc.diagnose(signal_id))
    hypothesis = record.provider_hypothesis
    assert record.status == "awaiting_review"
    assert hypothesis.supporting_evidence[0].item_id == svc.evidence(signal_id).items[0].item_id
    assert hypothesis.provider_metadata.provider == "Amazon Bedrock"
    assert hypothesis.provider_metadata.model == "global.anthropic.claude-sonnet-4-6"
    assert hypothesis.provider_metadata.invocation_region == "us-east-1"
    assert hypothesis.provider_metadata.invocation_id == "synthetic-request-id"
    assert hypothesis.provider_metadata.generation_mode == "provider"
    assert hypothesis.provider_metadata.generated_at is not None
    call = runtime.calls[0]
    assert call["modelId"] == "global.anthropic.claude-sonnet-4-6"
    assert call["messages"][0]["role"] == "user" and call["system"][0]["text"]
    assert "Person One" not in json.dumps(call)


def test_provider_error_is_sanitized_and_never_falls_back():
    svc, runtime, signal_id = service(FakeRuntime(error=RuntimeError("secret AWS detail")))
    prior = (app.state.diagnostics, app.state.demo_mode)
    try:
        app.state.diagnostics = svc
        app.state.demo_mode = "synthetic_test"
        assert TestClient(app).get("/diagnostics/mode").json()["diagnostic_provider"] == "provider"
        result = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
        assert result.status_code == 502
        assert result.json()["detail"] == {"code": "reasoner_failure", "message": "Reasoning provider failed"}
        assert "secret" not in result.text
        assert len(runtime.calls) == 1 and svc.list_hypotheses(signal_id) == []
    finally:
        app.state.diagnostics, app.state.demo_mode = prior


def test_real_mode_with_bedrock_installed_blocks_before_aws(monkeypatch):
    settings = Settings(bedrock_enabled=True, _env_file=None)
    monkeypatch.setattr(demo, "get_settings", lambda: settings)
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        demo.install_results_cx_demo(app, evaluations())
        assert isinstance(app.state.diagnostics.reasoner, BedrockReasoner)
        assert TestClient(app).get("/diagnostics/mode").json()["diagnostic_provider"] == "provider"
        runtime = FakeRuntime()
        app.state.diagnostics.reasoner._client = runtime
        signal_id = app.state.diagnostics.list_signals()[0].signal_id
        response = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "provider_privacy_blocked"
        assert runtime.calls == []
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_unavailable_mode_unchanged():
    svc = DiagnosticService(evaluations(), UnavailableReasoner())
    signal_id = svc.list_signals()[0].signal_id
    with pytest.raises(Exception, match="No diagnostic reasoning provider"):
        asyncio.run(svc.diagnose(signal_id))


def test_parse_response_rejects_cross_signal_reference():
    with pytest.raises(ProviderOutputError):
        parse_response(response(supporting_evidence_ids=["EVID-002"]),
                       {"EVID-001": ("ev_local", "eval_local")})
