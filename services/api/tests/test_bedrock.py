"""Synthetic-only AWS boundary tests; no network or credentials."""

import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.diagnostics.bedrock import (FIELD_GUIDANCE, ITEM_PAYLOAD_KEYS, REASONING_PROMPT,
                                     RESPONSE_SHAPE_EXAMPLE, SIGNAL_PAYLOAD_KEYS, SYSTEM_PROMPT,
                                     BedrockReasoner, BedrockResponse, parse_response,
                                     provider_safe_payload, response_contract)
from app.diagnostics.engine import (ControlledTestReasoner, DiagnosticService, ProviderOutputError,
                                    UnavailableReasoner, provider_kind, remote_invocation_policy)
from app.main import app
from app.results_cx import demo
from test_diagnostics import evaluations, prepared
from test_diagnostics import response as fixture_response


def response(**changes):
    base = {"observed_behavioral_defect": "Synthetic closing check failed",
            "cause_domain": "undetermined", "performance_dimension": "undetermined",
            "explanation": "The structured checks do not distinguish causes.",
            "supporting_evidence_ids": ["EVID-001"], "conflicting_evidence_ids": [],
            "missing_evidence": ["A direct observation of the workflow"],
            "provider_reported_confidence": 0.2}
    return json.dumps(base | changes)


class FakeRuntime:
    def __init__(self, text=None, error=None, stop_reason="end_turn"):
        self.text = response() if text is None else text
        self.error = error
        self.stop_reason = stop_reason
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"output": {"message": {"content": [{"text": self.text}]}},
                "stopReason": self.stop_reason,
                "ResponseMetadata": {"RequestId": "synthetic-request-id"}}


def synthetic_reasoner(rows, client=None):
    return BedrockReasoner.for_synthetic_evaluations("us-east-1", "global.anthropic.claude-sonnet-4-6",
                                                     rows, client=client or FakeRuntime())


def service(client=None, synthetic=True):
    runtime = client or FakeRuntime()
    rows = evaluations()
    reasoner = synthetic_reasoner(rows, runtime) if synthetic else BedrockReasoner(client=runtime)
    svc = DiagnosticService(rows, reasoner)
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
    assert remote_invocation_policy(BedrockReasoner()) == "privacy_blocked"
    assert remote_invocation_policy(synthetic_reasoner(evaluations())) == "synthetic_only"
    assert remote_invocation_policy(UnavailableReasoner()) == "unavailable"
    assert remote_invocation_policy(ControlledTestReasoner({})) == "local_fixture"

    class SelfDescribing:
        remote_invocation_policy = "permitted"  # Not a value a provider may declare.

        async def diagnose(self, bundle):
            return {}

    assert remote_invocation_policy(SelfDescribing()) == "undeclared"


def test_no_setting_or_environment_unlocks_synthetic_invocation(monkeypatch):
    """Only `for_synthetic_evaluations` unlocks; there is no setting, alias, or flag for it."""
    for name in ("COACHLENS_BEDROCK_SYNTHETIC_EVIDENCE", "COACHLENS_API_BEDROCK_SYNTHETIC_EVIDENCE",
                 "COACHLENS_API_SYNTHETIC", "COACHLENS_BEDROCK_SYNTHETIC", "COACHLENS_API_DIAGNOSTIC_PROVIDER"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("COACHLENS_BEDROCK_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert not any("synthetic" in field for field in Settings.model_fields)
    assert settings.bedrock_enabled is True
    # Constructed exactly as main.py and demo.py construct it.
    reasoner = BedrockReasoner(settings.bedrock_region, settings.bedrock_model_id)
    assert reasoner.remote_invocation_policy == "privacy_blocked"
    runtime = FakeRuntime()
    reasoner._client = runtime
    svc = DiagnosticService(evaluations(), reasoner)
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(svc.diagnose(svc.list_signals()[0].signal_id))
    assert refused.value.code == "provider_privacy_blocked"
    assert runtime.calls == []
    with pytest.raises(TypeError):
        BedrockReasoner(synthetic_evidence=True)  # The old boolean no longer exists.


def test_normal_api_process_with_bedrock_enabled_and_local_records_cannot_invoke(tmp_path):
    """The real `app.main` startup path, in a fresh process, with every knob an operator could set."""
    records = tmp_path / "evaluations.jsonl"
    records.write_text("".join(e.model_dump_json() + "\n" for e in evaluations()))
    script = """
import json, sys
from fastapi.testclient import TestClient
from app.main import app
from app.diagnostics.bedrock import BedrockReasoner
class Runtime:
    calls = []
    def converse(self, **kwargs):
        Runtime.calls.append(kwargs); raise AssertionError("Bedrock reached")
reasoner = app.state.diagnostics.reasoner
assert isinstance(reasoner, BedrockReasoner) and reasoner._client is None
reasoner._client = Runtime()
client = TestClient(app)
mode = client.get("/diagnostics/mode").json()
signal_id = client.get("/diagnostics/signals").json()[0]["signal_id"]
result = client.post(f"/diagnostics/signals/{signal_id}/hypotheses")
print(json.dumps({"mode": mode, "status": result.status_code, "detail": result.json()["detail"],
                  "calls": len(Runtime.calls),
                  "stored": client.get(f"/diagnostics/signals/{signal_id}/hypotheses").json()}))
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COACHLENS_", "AWS_"))}
    env.update({"COACHLENS_BEDROCK_ENABLED": "true", "COACHLENS_API_BEDROCK_ENABLED": "true",
                "COACHLENS_API_DIAGNOSTIC_EVALUATIONS_PATH": str(records),
                "COACHLENS_BEDROCK_SYNTHETIC_EVIDENCE": "true", "COACHLENS_API_DIAGNOSTIC_PROVIDER": "bedrock",
                "AWS_ACCESS_KEY_ID": "not-a-real-key-id", "AWS_SECRET_ACCESS_KEY": "not-a-real-secret",
                "AWS_DEFAULT_REGION": "us-east-1", "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
    completed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True,
                               cwd=Path(__file__).resolve().parents[1], timeout=120)
    assert completed.returncode == 0, completed.stderr[-2000:]
    out = json.loads(completed.stdout.strip().splitlines()[-1])
    assert out["mode"]["mode"] == "local_normalized"
    assert out["mode"]["diagnostic_provider"] == "provider"
    assert out["mode"]["remote_diagnosis"] == "privacy_blocked"
    assert out["status"] == 502 and out["detail"]["code"] == "provider_privacy_blocked"
    assert out["calls"] == 0 and out["stored"] == []
    assert "Person One" not in completed.stdout and "missed greeting" not in completed.stdout


def test_synthetic_binding_refuses_other_records():
    """A synthetic-bound reasoner sends nothing for a service holding different or extra records."""
    synthetic_rows = evaluations()
    other_rows = [row.model_copy(update={"internal_id": f"rcx_{index}"}) for index, row in enumerate(evaluations())]
    runtime = FakeRuntime()
    reasoner = synthetic_reasoner(synthetic_rows, runtime)
    for rows in (other_rows, synthetic_rows + [other_rows[0]]):
        svc = DiagnosticService(rows, reasoner)
        with pytest.raises(ProviderOutputError) as refused:
            asyncio.run(svc.diagnose(svc.list_signals()[0].signal_id))
        assert refused.value.code == "provider_privacy_blocked"
        assert runtime.calls == [] and svc.list_hypotheses(svc.list_signals()[0].signal_id) == []
    with pytest.raises(ValueError):
        BedrockReasoner.for_synthetic_evaluations("us-east-1", "m", [])
    with pytest.raises(ValueError):
        BedrockReasoner.for_synthetic_evaluations("us-east-1", "m", [synthetic_rows[0], synthetic_rows[0]])
    svc = DiagnosticService(synthetic_rows, reasoner)
    assert asyncio.run(svc.diagnose(svc.list_signals()[0].signal_id)).status == "awaiting_review"
    assert len(runtime.calls) == 1


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


def test_request_contains_only_allowlisted_fields():
    """Positive allowlist: the whole Converse request is enumerable, not just free of known strings."""
    rows = evaluations()
    rows[0].criteria[0] = rows[0].criteria[0].model_copy(update={
        "evaluator_feedback": "member DOB 01/02/1950 condition X; Person One forgot the script",
        "answer": "Free text answer that must not travel"})
    rows[0] = rows[0].model_copy(update={"agent_name": "Sensitive Agent Name"})
    runtime = FakeRuntime()
    svc = DiagnosticService(rows, synthetic_reasoner(rows, runtime))
    signal_id = svc.list_signals()[0].signal_id
    asyncio.run(svc.diagnose(signal_id))
    call = runtime.calls[0]
    assert set(call) == {"modelId", "system", "messages", "inferenceConfig"}
    assert call["system"] == [{"text": SYSTEM_PROMPT}]
    assert call["inferenceConfig"] == {"maxTokens": 1200, "temperature": 0}
    assert len(call["messages"]) == 1 and call["messages"][0]["role"] == "user"
    content = call["messages"][0]["content"]
    assert len(content) == 1 and set(content[0]) == {"text"}
    body = json.loads(content[0]["text"])
    assert set(body) == {"signal", "evidence_items"}
    assert set(body["signal"]) == SIGNAL_PAYLOAD_KEYS
    assert body["evidence_items"] and all(set(item) == ITEM_PAYLOAD_KEYS for item in body["evidence_items"])
    for item in body["evidence_items"]:
        assert item["reference"].startswith("EVID-") and isinstance(item["failed"], bool)
    leaves = [value for item in [body["signal"], *body["evidence_items"]] for value in item.values()]
    assert all(isinstance(value, (str, int, bool)) for value in leaves)
    wire = json.dumps(call)
    for forbidden in ("DOB", "condition X", "Free text", "Sensitive Agent", "Person One", "Reviewer",
                      "Lead One", "eval_1", "eval_2", "sig_", "ev_", "synthetic.xlsx", "Sheet",
                      "missed greeting", "1950"):
        assert forbidden not in wire, forbidden
    assert "/" not in content[0]["text"] and "\\" not in content[0]["text"]  # No path fragments.
    # The bundle the reasoner received did carry the feedback; the request did not.
    assert svc.provider_evidence(signal_id).items[0].evaluator_feedback


def test_coverage_incomplete_dataset_is_preserved():
    rows = evaluations()
    rows.append(rows[0].model_copy(update={"internal_id": "eval_3", "criteria": []}))
    svc = DiagnosticService(rows, synthetic_reasoner(rows))
    payload, _ = provider_safe_payload(svc.provider_evidence(svc.list_signals()[0].signal_id))
    assert payload["signal"]["failure_rate"] == "1"
    assert payload["signal"]["failed_criterion_result_count"] == 2
    assert payload["signal"]["evaluated_criterion_result_count"] == 2
    assert payload["signal"]["evaluations_containing_criterion"] == 2
    assert payload["signal"]["total_loaded_evaluations"] == 3
    assert "total_loaded_evaluations is the whole loaded dataset" in SYSTEM_PROMPT
    assert "Do not recalculate" in SYSTEM_PROMPT and "Do not\nautomatically recommend training" in SYSTEM_PROMPT


@pytest.mark.parametrize("bad", [
    "not-json", response(cause_domain="will_gap"), response(provider_reported_confidence=2),
    response(supporting_evidence_ids=["EVID-999"]),
    response(supporting_evidence_ids=["EVID-003"]),  # Bundle has two items; the third does not exist.
    response(supporting_evidence_ids=["EVID-001", "EVID-001"]),
    response(conflicting_evidence_ids=["EVID-001"]),
    response(supporting_evidence_ids=["SIGNAL-001"], conflicting_evidence_ids=["SIGNAL-001"]),
    response(supporting_evidence_ids=[""]), response(supporting_evidence_ids=["evid-001"]),
    response(supporting_evidence_ids=["ev_deadbeef"]), response(supporting_evidence_ids=[1]),
    response(explanation=""), response(explanation="   "), response(missing_evidence=[]),
    response(provider_reported_confidence=True), response(provider_reported_confidence=-0.1),
    response().replace("0.2", "NaN"), response().replace("0.2", "Infinity"),
    "```json\n" + response() + "\n```", response()[:-15], "[" * 5000,
    response(explanation="a" * 4001), response(missing_evidence=["a" * 4001]),
    response(hypothesis_id="forged"), response(signal_id="forged"),
    response(provider_metadata={"provider": "fixture", "generation_mode": "controlled_fixture"}),
    response(source_lineage={"source_filename": "forbidden"}),
])
def test_strict_response_rejection(bad):
    svc, _, signal_id = service(FakeRuntime(bad))
    with pytest.raises(ProviderOutputError):
        asyncio.run(svc.diagnose(signal_id))
    assert svc.list_hypotheses(signal_id) == []


@pytest.mark.parametrize("shape", [
    {"output": {"message": {"content": []}}},
    {"output": {"message": {"content": [{"text": response()}, {"text": "more"}]}}},
    {"output": {"message": {"content": [{"image": {}}]}}},
    {"output": {"message": {"content": [{"text": response(), "toolUse": {}}]}}},
    {"output": {"message": {"content": {"text": response()}}}},
    {"ResponseMetadata": {"RequestId": "x"}},
    {"output": {"message": {"content": [{"text": response()}]}}, "stopReason": "max_tokens"},
    {"output": {"message": {"content": [{"text": response()}]}}, "stopReason": "guardrail_intervened"},
    {"output": {"message": {"content": [{"text": response()}]}}, "stopReason": "content_filtered"},
])
def test_malformed_converse_shapes_fail_closed(shape):
    class ShapedRuntime:
        def converse(self, **kwargs):
            return shape

    rows = evaluations()
    svc = DiagnosticService(rows, synthetic_reasoner(rows, ShapedRuntime()))
    signal_id = svc.list_signals()[0].signal_id
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(svc.diagnose(signal_id))
    assert refused.value.code in {"reasoner_failure", "invalid_provider_output"}
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
    assert hypothesis.provider_metadata.generated_at.tzinfo is not None
    assert hypothesis.hypothesis_id.startswith("bedrock_")
    call = runtime.calls[0]
    assert call["modelId"] == "global.anthropic.claude-sonnet-4-6"
    assert call["messages"][0]["role"] == "user" and call["system"][0]["text"]
    assert "Person One" not in json.dumps(call)
    # Odd request IDs are dropped rather than stored.
    for weird in (12345, "r" * 300):
        runtime = FakeRuntime()
        runtime.converse = lambda **kw: {"output": {"message": {"content": [{"text": response()}]}},
                                         "stopReason": "end_turn", "ResponseMetadata": {"RequestId": weird}}
        rows = evaluations()
        svc = DiagnosticService(rows, synthetic_reasoner(rows, runtime))
        assert asyncio.run(svc.diagnose(svc.list_signals()[0].signal_id)).provider_hypothesis \
            .provider_metadata.invocation_id is None


def test_generation_mode_derives_from_installed_object_not_output():
    """Bedrock output gets `provider`; a fixture cannot forge it; provider claims are refused."""
    source, signal, bundle = prepared()
    fixture = ControlledTestReasoner(fixture_response(bundle))
    record = asyncio.run(DiagnosticService(source, fixture).diagnose(signal.signal_id))
    assert record.provider_hypothesis.provider_metadata.generation_mode == "controlled_fixture"
    assert record.provider_hypothesis.provider_metadata.provider == "controlled-test"
    forged = fixture_response(bundle)
    forged["provider_metadata"] = {"provider": "Amazon Bedrock", "model": "global.anthropic.claude-sonnet-4-6",
                                   "invocation_region": "us-east-1", "generation_mode": "provider"}
    svc = DiagnosticService(source, ControlledTestReasoner(forged))
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(svc.diagnose(signal.signal_id))
    assert refused.value.code == "invalid_provider_output"
    assert svc.list_hypotheses(signal.signal_id) == []
    # Serialization of pre-AWS-1 metadata is unchanged, and the stamped field appears once set.
    plain = fixture_response(bundle)
    dumped = asyncio.run(DiagnosticService(source, ControlledTestReasoner(plain)).diagnose(signal.signal_id)) \
        .provider_hypothesis.provider_metadata.model_dump(mode="json")
    assert dumped == {"provider": "controlled-test", "model": None, "generation_mode": "controlled_fixture"}


def test_provider_error_is_sanitized_and_never_falls_back():
    svc, runtime, signal_id = service(FakeRuntime(error=RuntimeError("secret AWS detail")))
    prior = (app.state.diagnostics, app.state.demo_mode)
    try:
        app.state.diagnostics = svc
        app.state.demo_mode = "synthetic_test"
        mode = TestClient(app).get("/diagnostics/mode").json()
        assert mode["diagnostic_provider"] == "provider" and mode["remote_diagnosis"] == "synthetic_only"
        result = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
        assert result.status_code == 502
        assert result.json()["detail"] == {"code": "reasoner_failure", "message": "Reasoning provider failed"}
        assert "secret" not in result.text
        assert len(runtime.calls) == 1 and svc.list_hypotheses(signal_id) == []
        assert isinstance(app.state.diagnostics.reasoner, BedrockReasoner)  # No fixture swapped in.
    finally:
        app.state.diagnostics, app.state.demo_mode = prior


def test_aws_client_errors_are_sanitized():
    from botocore.exceptions import ClientError, NoCredentialsError

    errors = [
        ClientError({"Error": {"Code": "AccessDeniedException",
                               "Message": "User: arn:aws:sts::123456789012:assumed-role/x is not authorized"},
                     "ResponseMetadata": {"RequestId": "req-secret", "HTTPStatusCode": 403}}, "Converse"),
        ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}}, "Converse"),
        ClientError({"Error": {"Code": "ExpiredTokenException", "Message": "token expired"}}, "Converse"),
        NoCredentialsError(),
        ConnectionError("network down"),
    ]
    for error in errors:
        svc, runtime, signal_id = service(FakeRuntime(error=error))
        prior = app.state.diagnostics
        try:
            app.state.diagnostics = svc
            result = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
        finally:
            app.state.diagnostics = prior
        assert result.status_code == 502
        assert result.json()["detail"] == {"code": "reasoner_failure", "message": "Reasoning provider failed"}
        for leaked in ("123456789012", "arn:", "req-secret", "AccessDenied", "Throttling", "expired", "network"):
            assert leaked not in result.text
        assert svc.list_hypotheses(signal_id) == []


def test_reasoner_authored_error_text_never_reaches_clients():
    class LeakyReasoner:
        async def diagnose(self, bundle):
            raise ProviderOutputError("custom_code", "payload was " + json.dumps(bundle.model_dump(mode="json"))[:60])

    svc = DiagnosticService(evaluations(), LeakyReasoner())
    signal_id = svc.list_signals()[0].signal_id
    prior = app.state.diagnostics
    try:
        app.state.diagnostics = svc
        result = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
    finally:
        app.state.diagnostics = prior
    assert result.status_code == 502
    assert result.json()["detail"] == {"code": "reasoner_failure", "message": "Reasoning provider failed"}
    assert "payload" not in result.text and "Person" not in result.text


def test_real_mode_with_bedrock_installed_blocks_before_aws(monkeypatch):
    settings = Settings(bedrock_enabled=True, _env_file=None)
    monkeypatch.setattr(demo, "get_settings", lambda: settings)
    prior = (app.state.diagnostics, app.state.designs, app.state.demo_mode)
    try:
        demo.install_results_cx_demo(app, evaluations())
        assert isinstance(app.state.diagnostics.reasoner, BedrockReasoner)
        mode = TestClient(app).get("/diagnostics/mode").json()
        # AWS-4 installs Bedrock intervention providers behind the same switch; the M5 step
        # that reads their record is therefore a provider, while the training designer is not.
        assert mode == {"mode": "real_results_cx", "diagnostic_provider": "provider",
                        "remote_diagnosis": "privacy_blocked", "design_provider": "provider",
                        "intervention_provider": "provider", "solution_validator": "provider",
                        "evaluation_count": 2, "signal_count": 2}
        runtime = FakeRuntime()
        app.state.diagnostics.reasoner._client = runtime
        signal_id = app.state.diagnostics.list_signals()[0].signal_id
        response = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "provider_privacy_blocked"
        assert runtime.calls == []
        assert TestClient(app).get(f"/diagnostics/signals/{signal_id}/hypotheses").json() == []
    finally:
        app.state.diagnostics, app.state.designs, app.state.demo_mode = prior


def test_unavailable_mode_unchanged():
    svc = DiagnosticService(evaluations(), UnavailableReasoner())
    signal_id = svc.list_signals()[0].signal_id
    with pytest.raises(Exception, match="No diagnostic reasoning provider") as failure:
        asyncio.run(svc.diagnose(signal_id))
    assert failure.value.code == "reasoner_unavailable"


def test_parse_response_rejects_cross_signal_reference():
    with pytest.raises(ProviderOutputError):
        parse_response(response(supporting_evidence_ids=["EVID-002"]),
                       {"EVID-001": ("ev_local", "eval_local")})


def test_missing_evidence_is_descriptive_not_a_citation():
    """Missing evidence text may mention a reference but never becomes a stored citation."""
    svc, _, signal_id = service(FakeRuntime(response(missing_evidence=["EVID-002 call recording"])))
    record = asyncio.run(svc.diagnose(signal_id))
    assert record.provider_hypothesis.missing_evidence == ["EVID-002 call recording"]
    cited = {r.item_id for r in record.provider_hypothesis.supporting_evidence}
    assert cited == {svc.evidence(signal_id).items[0].item_id}


def test_smoke_script_synthetic_path_invokes_with_expected_coverage(monkeypatch):
    """The only sanctioned remote path: the smoke script's in-memory records, with a stub client."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "smoke", Path(__file__).resolve().parents[3] / "scripts" / "run_bedrock_synthetic_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    rows = smoke.synthetic_evaluations()
    assert len(rows) == 4 and all(row.internal_id.startswith("synthetic_") for row in rows)
    runtime = FakeRuntime()
    svc = DiagnosticService(rows, smoke.BedrockReasoner.for_synthetic_evaluations("us-east-1", "m", rows,
                                                                                 client=runtime))
    signal = svc.list_signals()[0]
    record = asyncio.run(svc.diagnose(signal.signal_id))
    assert record.status == "awaiting_review"
    assert (signal.fail_count, signal.evaluated_results, signal.evaluated_evaluations,
            signal.total_evaluations) == (3, 3, 3, 4)
    sent = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])["signal"]
    assert sent["failed_criterion_result_count"] == 3 and sent["evaluated_criterion_result_count"] == 3
    assert sent["evaluations_containing_criterion"] == 3 and sent["total_loaded_evaluations"] == 4
    assert sent["failure_rate"] == "1"
    assert "Synthetic placeholder comment" not in json.dumps(runtime.calls[0])
    assert "Synthetic Agent" not in json.dumps(runtime.calls[0])
    # The script refuses to run against a configured local evaluations file.
    monkeypatch.setattr(smoke, "get_settings",
                        lambda: Settings(diagnostic_evaluations_path=Path("x.jsonl"), bedrock_enabled=True,
                                         _env_file=None))
    with pytest.raises(SystemExit, match="refuses a configured local evaluations path"):
        asyncio.run(smoke.main())


# --- Output-contract hardening (post live-smoke) -------------------------------------------
# The first live Sonnet 4.6 smoke returned `missing_evidence` as a bare string and
# `provider_reported_confidence` as the label "low_to_moderate". Validation refused both and
# stored nothing, which is correct. These tests pin the prompt that now forbids those shapes
# and prove the validator was not loosened to accept them.

EXPECTED_PROMPT_TYPES = {
    "observed_behavioral_defect": "JSON string of 1 to 4000 characters",
    "cause_domain": 'JSON string, exactly one of "knowledge_gap", "skill_gap", "process_gap", "undetermined"',
    "performance_dimension": 'JSON string, exactly one of "capability", "execution", "undetermined"',
    "explanation": "JSON string of 1 to 4000 characters",
    "supporting_evidence_ids": "JSON array of 1 to 100 JSON strings",
    "conflicting_evidence_ids": "JSON array of 0 to 100 JSON strings",
    "missing_evidence": "JSON array of 0 to 100 JSON strings",
    "provider_reported_confidence": "JSON number from 0 to 1 inclusive",
}


def test_prompt_contract_specifies_every_response_field_type():
    """Every BedrockResponse field is named in the prompt with its exact JSON type and bounds."""
    assert set(EXPECTED_PROMPT_TYPES) == set(BedrockResponse.model_fields) == set(FIELD_GUIDANCE)
    contract = response_contract()
    assert SYSTEM_PROMPT == REASONING_PROMPT + "\n\n" + contract
    for name, expected in EXPECTED_PROMPT_TYPES.items():
        assert f'- "{name}": {expected}. ' in contract, name
    assert contract.count("\n- ") == len(BedrockResponse.model_fields)
    assert "exactly these 8 keys, all required, and no other keys" in contract
    # The two live failures, called out explicitly.
    assert '- "missing_evidence": JSON array' in contract
    assert "ALWAYS a JSON array of strings, even when there is exactly one item; use [] when" in contract
    assert '- "provider_reported_confidence": JSON number' in contract
    assert "ALWAYS a JSON number literal such as 0.35, never a string" in contract
    for label in ('"low"', '"moderate"', '"high"', '"low_to_moderate"', '"35%"'):
        assert label in contract
    assert "are invalid" in contract
    # Envelope, enum, evidence, and lineage rules.
    assert "Return exactly one JSON object and nothing else" in contract
    assert "no markdown, no code fences, and no prose" in contract
    assert "Never invent, alter, renumber, or repeat a reference" in contract
    assert "must not appear in both supporting_evidence_ids and conflicting_evidence_ids" in contract
    assert "Do not include hypothesis_id, signal_id, provider_metadata, generation_mode, source lineage" in contract
    assert "Do not add new statistics" in contract
    assert "discarded without repair" in contract
    # Coverage semantics and the no-recalculation rule survive in the reasoning half.
    assert "total_loaded_evaluations is the whole loaded dataset" in SYSTEM_PROMPT
    assert "Do not recalculate" in SYSTEM_PROMPT and "Do not\nautomatically recommend training" in SYSTEM_PROMPT
    assert "Cite at least one supplied reference, including SIGNAL-001" in SYSTEM_PROMPT


def test_prompt_shape_example_matches_validator():
    """The illustration is exactly what the validator accepts, so it cannot teach a bad shape."""
    assert list(RESPONSE_SHAPE_EXAMPLE) == list(BedrockResponse.model_fields)
    parsed = BedrockResponse.model_validate(RESPONSE_SHAPE_EXAMPLE)
    assert isinstance(parsed.missing_evidence, list) and len(parsed.missing_evidence) == 1
    assert isinstance(parsed.provider_reported_confidence, float)
    last_line = SYSTEM_PROMPT.rsplit("\n", 1)[1]
    assert json.loads(last_line) == RESPONSE_SHAPE_EXAMPLE
    assert "```" not in SYSTEM_PROMPT
    # A shape drift in the validator would surface here rather than in a live call.
    assert parse_response(last_line, {"SIGNAL-001": ("signal", None), "EVID-001": ("ev_x", "eval_x")})[
        "provider_reported_confidence"] == 0.25


LIVE_SMOKE_SHAPES = {
    "live_sonnet_both_mismatches": response(missing_evidence="A direct observation of the workflow",
                                            provider_reported_confidence="low_to_moderate"),
    "string_missing_evidence": response(missing_evidence="A direct observation of the workflow"),
    "label_low_to_moderate": response(provider_reported_confidence="low_to_moderate"),
    "label_low": response(provider_reported_confidence="low"),
    "label_moderate": response(provider_reported_confidence="moderate"),
    "label_high": response(provider_reported_confidence="high"),
    "numeric_string": response(provider_reported_confidence="0.4"),
    "percentage_string": response(provider_reported_confidence="35%"),
    "null_missing_evidence": response(missing_evidence=None),
    "object_missing_evidence": response(missing_evidence={"item": "x"}),
}


@pytest.mark.parametrize("text", LIVE_SMOKE_SHAPES.values(), ids=list(LIVE_SMOKE_SHAPES))
def test_live_smoke_shapes_still_fail_closed_without_repair_or_fallback(text):
    runtime = FakeRuntime(text)
    svc, _, signal_id = service(runtime)
    with pytest.raises(ProviderOutputError) as refused:
        asyncio.run(svc.diagnose(signal_id))
    assert refused.value.code == "invalid_provider_output"
    assert len(runtime.calls) == 1  # No retry, no repair round-trip.
    assert svc.list_hypotheses(signal_id) == []
    assert isinstance(svc.reasoner, BedrockReasoner)  # No fixture fallback.
    # The request that produced the failure is still the prompt-only Converse call: no
    # outputConfig / toolConfig was introduced, and the system text is the hardened contract.
    call = runtime.calls[0]
    assert set(call) == {"modelId", "system", "messages", "inferenceConfig"}
    assert call["system"] == [{"text": SYSTEM_PROMPT}]
    assert "json_schema" not in json.dumps(call["inferenceConfig"])
    # The HTTP surface stays sanitized and leaks neither the label nor the model text.
    prior = app.state.diagnostics
    try:
        app.state.diagnostics = svc
        result = TestClient(app).post(f"/diagnostics/signals/{signal_id}/hypotheses")
    finally:
        app.state.diagnostics = prior
    assert result.status_code == 502
    assert result.json()["detail"] == {"code": "invalid_provider_output",
                                       "message": "Reasoner returned an invalid hypothesis"}
    assert "low_to_moderate" not in result.text and "missing_evidence" not in result.text
    assert len(runtime.calls) == 2 and svc.list_hypotheses(signal_id) == []


def test_valid_output_after_hardening_keeps_local_stamping_and_coverage():
    """A conforming response is stored with locally stamped provenance and unchanged coverage."""
    svc, runtime, signal_id = service(FakeRuntime(response(missing_evidence=["One item"],
                                                            provider_reported_confidence=0.35)))
    record = asyncio.run(svc.diagnose(signal_id))
    hypothesis = record.provider_hypothesis
    assert hypothesis.missing_evidence == ["One item"]
    assert hypothesis.provider_reported_confidence == Decimal("0.35")
    assert hypothesis.provider_metadata.generation_mode == "provider"  # Stamped by the service.
    assert "generation_mode" not in SYSTEM_PROMPT.rsplit("\n", 1)[1]  # Never requested from the model.
    sent = json.loads(runtime.calls[0]["messages"][0]["content"][0]["text"])["signal"]
    assert (sent["failed_criterion_result_count"], sent["evaluated_criterion_result_count"],
            sent["evaluations_containing_criterion"], sent["total_loaded_evaluations"]) == (2, 2, 2, 2)
    assert set(sent) == SIGNAL_PAYLOAD_KEYS
