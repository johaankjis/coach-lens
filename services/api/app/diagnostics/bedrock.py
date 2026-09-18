"""Bedrock diagnostic adapter with synthetic and trusted local ResultsCX gates.

The M3 provider view is for local use and can contain confidential feedback. It must never
be serialized into a Bedrock request. This module constructs a separate allowlisted payload.
"""

import asyncio
from datetime import datetime, timezone
import json
from uuid import uuid4

from pydantic import Field, ValidationError

from app.results_cx.models import Domain, Evaluation

from .engine import ProviderOutputError
from .models import (CauseDomain, PerformanceDimension, ProviderEvidenceBundle,
                     StrictModel)


REASONING_PROMPT = """You propose why a recurring observed QA pattern might be happening.
CoachLens supplies deterministic QA facts. Do not recalculate, override, or reinterpret
source QA pass/fail results. Failure frequency alone does not establish root cause.
Counts and rates describe only the criterion results that were evaluated;
evaluations_containing_criterion is how many evaluations contain this criterion, and
total_loaded_evaluations is the whole loaded dataset, which may be larger. Never treat
failed results over total_loaded_evaluations as a rate, and never infer that evaluations
without this criterion passed or failed it.
Diagnosis is a proposal, not truth. Do not invent evidence or cite anything outside the
supplied evidence references. Distinguish supporting from conflicting evidence, and identify
missing evidence. Return undetermined when the evidence cannot distinguish causes. Do not
automatically recommend training. A human validates the diagnosis afterward.
Cite at least one supplied reference, including SIGNAL-001 when only aggregate evidence
supports the observation.
Qualitative evaluator feedback may have been withheld from you by local policy.
text_coverage states how many evidence items have local feedback and how many of those were
withheld or blocked; absence of diagnostic_text never means no local feedback existed. Never
invent, guess, or paraphrase withheld feedback. When the qualitative evidence you were given
is insufficient to distinguish causes, lower provider_reported_confidence or return
undetermined and name the missing evidence. diagnostic_text, when present, is locally
minimized evaluator feedback in which [redacted] marks a suppressed staff name; treat it as
an unnamed person. High failure rate alone does not establish a training need."""

# Meaning of each response field. Types, enums, and bounds are NOT written here: they are
# rendered from the BedrockResponse JSON schema so the prompt cannot drift from the validator.
FIELD_GUIDANCE = {
    "observed_behavioral_defect": "The recurring behavior the deterministic facts show.",
    "cause_domain": "Use undetermined when the evidence cannot distinguish causes.",
    "performance_dimension": "Use undetermined when the evidence does not distinguish.",
    "explanation": "Why the cited evidence supports this proposal.",
    "supporting_evidence_ids": "Each entry is one supplied reference (SIGNAL-001 or an EVID-### "
                               "value from evidence_items) copied exactly. Never invent, alter, "
                               "renumber, or repeat a reference.",
    "conflicting_evidence_ids": "Same reference rule. A reference must not appear in both "
                                "supporting_evidence_ids and conflicting_evidence_ids.",
    "missing_evidence": "Short descriptions of evidence that would distinguish causes. ALWAYS a "
                        "JSON array of strings, even when there is exactly one item; use [] when "
                        "nothing is missing. Must be non-empty when cause_domain is undetermined.",
    "provider_reported_confidence": "ALWAYS a JSON number literal such as 0.35, never a string. "
                                    "Qualitative labels such as \"low\", \"moderate\", \"high\", "
                                    "\"low_to_moderate\", and percentages such as \"35%\" are invalid.",
}

# Shape illustration only: it shows the JSON type of every field, not values to copy.
RESPONSE_SHAPE_EXAMPLE = {
    "observed_behavioral_defect": "string", "cause_domain": CauseDomain.UNDETERMINED.value,
    "performance_dimension": PerformanceDimension.UNDETERMINED.value, "explanation": "string",
    "supporting_evidence_ids": ["SIGNAL-001", "EVID-001"], "conflicting_evidence_ids": [],
    "missing_evidence": ["string"], "provider_reported_confidence": 0.25}


def _describe_type(prop: dict) -> str:
    """Render one JSON-schema property as a plain-language type with its bounds."""
    if "enum" in prop:
        return "JSON string, exactly one of " + ", ".join(f'"{value}"' for value in prop["enum"])
    kind = prop["type"]
    if kind == "string":
        return f"JSON string of {prop.get('minLength', 0)} to {prop['maxLength']} characters"
    if kind == "array":
        return (f"JSON array of {prop.get('minItems', 0)} to {prop['maxItems']} "
                f"JSON {prop['items']['type']}s")
    if kind == "number":
        return f"JSON number from {prop['minimum']} to {prop['maximum']} inclusive"
    raise TypeError(f"Unsupported response field type: {kind}")


def response_contract() -> str:
    """The exact output contract, rendered from the BedrockResponse schema.

    Anything the schema cannot express (reference rules, the array-even-when-single rule, the
    number-never-label rule) is stated in FIELD_GUIDANCE. Local validation stays authoritative;
    this text only tells the model what that validation will accept.
    """
    schema = BedrockResponse.model_json_schema()
    fields = list(schema["properties"])
    lines = [f"Output contract. Return exactly one JSON object and nothing else: no markdown, no code "
             f"fences, and no prose, labels, or comments before or after it. The object has exactly "
             f"these {len(fields)} keys, all required, and no other keys:"]
    for name in fields:
        prop = schema["properties"][name]
        if "$ref" in prop:
            prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[1]]
        lines.append(f'- "{name}": {_describe_type(prop)}. {FIELD_GUIDANCE.get(name, "")}'.rstrip())
    lines.append("Do not include hypothesis_id, signal_id, provider_metadata, generation_mode, source "
                 "lineage, model or provider names, or any key not listed above. Do not add new "
                 "statistics: report the supplied counts and rates as given or not at all. An object "
                 "that violates any rule above is discarded without repair, so a valid object that "
                 "says undetermined with honest missing_evidence is better than an invalid one.")
    lines.append("Shape illustration with placeholder values (copy the types, not the values):")
    lines.append(json.dumps(RESPONSE_SHAPE_EXAMPLE))
    return "\n".join(lines)


PROVIDER_NAME = "Amazon Bedrock"

# The only keys a Converse request may carry. Tests assert against these, so a new field
# must be added here deliberately rather than appearing through serialization.
SIGNAL_PAYLOAD_KEYS = frozenset({
    "reference", "domain", "criterion", "failed_criterion_result_count",
    "passed_criterion_result_count", "evaluated_criterion_result_count", "failure_rate",
    "pass_rate", "evaluations_containing_criterion", "total_loaded_evaluations",
    "feedback_count", "feedback_coverage", "max_score_total", "attained_score_total",
    "score_rate"})
ITEM_PAYLOAD_KEYS = frozenset({"reference", "domain", "criterion", "failed", "max_score",
                               "attained_score"})
REAL_ITEM_PAYLOAD_KEYS = ITEM_PAYLOAD_KEYS | {"diagnostic_text"}
TEXT_COVERAGE_KEYS = frozenset({"total_evidence_items", "evidence_items_with_feedback",
                                "minimized_text_items_allowed", "text_items_blocked",
                                "text_items_with_no_text"})
_DOMAINS = frozenset(domain.value for domain in Domain)
MAX_TEXT_LENGTH = 1000  # Mirrors evidence_policy; the validator must not import policy state.


class BedrockResponse(StrictModel):
    observed_behavioral_defect: str = Field(min_length=1, max_length=4000)
    cause_domain: CauseDomain
    performance_dimension: PerformanceDimension
    explanation: str = Field(min_length=1, max_length=4000)
    supporting_evidence_ids: list[str] = Field(min_length=1, max_length=100)
    conflicting_evidence_ids: list[str] = Field(max_length=100)
    missing_evidence: list[str] = Field(max_length=100)
    provider_reported_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


SYSTEM_PROMPT = REASONING_PROMPT + "\n\n" + response_contract()


def provider_safe_payload(bundle: ProviderEvidenceBundle) -> tuple[dict, dict[str, tuple[str, str | None]]]:
    """Project only structured facts and fresh opaque references.

    No feedback, free-text answer, local ID, lineage, name, filename, or sheet is copied.
    Synthetic callers certify their input. The real preparation path applies its criterion
    policy before transmission. The returned lookup stays local to restore M3 citations.
    """
    signal = bundle.signal
    if (signal.evaluated_results != len(bundle.items) or
            signal.evaluated_evaluations > signal.total_evaluations or
            signal.fail_count + signal.pass_count != signal.evaluated_results or
            signal.feedback_count > signal.evaluated_results):
        raise ProviderOutputError("invalid_provider_input", "Diagnostic evidence coverage is inconsistent")
    lookup = {"SIGNAL-001": ("signal", None)}
    items = []
    for number, item in enumerate(bundle.items, 1):
        if item.domain != signal.domain or item.criterion != signal.criterion:
            raise ProviderOutputError("invalid_provider_input", "Diagnostic evidence does not match signal")
        ref = f"EVID-{number:03d}"
        lookup[ref] = (item.item_id, item.evaluation_id)
        items.append({"reference": ref, "domain": item.domain.value,
                      "criterion": item.criterion, "failed": not item.passed,
                      "max_score": str(item.max_score), "attained_score": str(item.attained_score)})
    payload = {"signal": {"reference": "SIGNAL-001", "domain": signal.domain.value,
                          "criterion": signal.criterion,
                          "failed_criterion_result_count": signal.fail_count,
                          "passed_criterion_result_count": signal.pass_count,
                          "evaluated_criterion_result_count": signal.evaluated_results,
                          "failure_rate": str(signal.fail_rate),
                          "pass_rate": str(signal.pass_rate),
                          "evaluations_containing_criterion": signal.evaluated_evaluations,
                          "total_loaded_evaluations": signal.total_evaluations,
                          "feedback_count": signal.feedback_count,
                          "feedback_coverage": str(signal.feedback_coverage),
                          "max_score_total": str(signal.max_score_total),
                          "attained_score_total": str(signal.attained_score_total),
                          "score_rate": str(signal.score_rate)},
               "evidence_items": items}
    if set(payload["signal"]) != SIGNAL_PAYLOAD_KEYS or any(set(item) != ITEM_PAYLOAD_KEYS for item in items):
        raise ProviderOutputError("invalid_provider_input", "Provider request projection drifted from allowlist")
    return payload, lookup


def validate_real_wire_payload(payload: dict) -> None:
    """Fail closed if a new field appears in the real Converse request."""
    if not isinstance(payload, dict):
        raise ProviderOutputError("invalid_provider_input", "Provider request projection drifted from allowlist")
    items = payload.get("evidence_items")
    coverage = payload.get("text_coverage")
    if (set(payload) != {"signal", "evidence_items", "text_coverage"} or
            not isinstance(payload["signal"], dict) or
            set(payload["signal"]) != SIGNAL_PAYLOAD_KEYS or
            not isinstance(items, list) or not isinstance(coverage, dict) or
            set(coverage) != TEXT_COVERAGE_KEYS):
        raise ProviderOutputError("invalid_provider_input", "Provider request projection drifted from allowlist")
    signal = payload["signal"]
    signal_strings = {"reference", "domain", "criterion", "failure_rate", "pass_rate",
                      "feedback_coverage", "max_score_total", "attained_score_total", "score_rate"}
    if (signal["reference"] != "SIGNAL-001" or
            any(not isinstance(signal[key], str) for key in signal_strings) or
            signal["domain"] not in _DOMAINS or len(signal["criterion"]) > MAX_TEXT_LENGTH or
            any(type(signal[key]) is not int or signal[key] < 0 for key in SIGNAL_PAYLOAD_KEYS - signal_strings) or
            any(type(coverage[key]) is not int or coverage[key] < 0 for key in TEXT_COVERAGE_KEYS) or
            coverage["total_evidence_items"] != len(items) or
            sum(coverage[key] for key in ("minimized_text_items_allowed", "text_items_blocked",
                                            "text_items_with_no_text")) != len(items) or
            coverage["evidence_items_with_feedback"] != signal["feedback_count"]):
        raise ProviderOutputError("invalid_provider_input", "Provider request projection drifted from allowlist")
    for number, item in enumerate(items, 1):
        if (not isinstance(item, dict) or set(item) not in (ITEM_PAYLOAD_KEYS, REAL_ITEM_PAYLOAD_KEYS) or
                item["reference"] != f"EVID-{number:03d}" or
                any(not isinstance(item[key], str) for key in ("domain", "criterion", "max_score",
                                                               "attained_score")) or
                item["domain"] not in _DOMAINS or item["domain"] != signal["domain"] or
                item["criterion"] != signal["criterion"] or type(item["failed"]) is not bool):
            raise ProviderOutputError("invalid_provider_input", "Provider request projection drifted from allowlist")
        if "diagnostic_text" in item and (not isinstance(item["diagnostic_text"], dict) or
                                          set(item["diagnostic_text"]) != {"kind", "text"} or
                                          item["diagnostic_text"]["kind"] != "minimized_evaluator_feedback" or
                                          not isinstance(item["diagnostic_text"]["text"], str) or
                                          not item["diagnostic_text"]["text"] or
                                          len(item["diagnostic_text"]["text"]) > MAX_TEXT_LENGTH):
            raise ProviderOutputError("invalid_provider_input", "Provider request projection drifted from allowlist")


def parse_response(text: str, lookup: dict[str, tuple[str, str | None]]) -> dict:
    try:
        raw = json.loads(text)
        # Confidence must arrive as a JSON number. Pydantic's lax mode would otherwise accept
        # a bool or a numeric string such as "0.4", which the contract tells the model is invalid.
        confidence = raw.get("provider_reported_confidence") if isinstance(raw, dict) else None
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("Invalid structured response")
        result = BedrockResponse.model_validate(raw)
    except (ValueError, TypeError, ValidationError) as exc:
        raise ProviderOutputError("invalid_provider_output", "Reasoner returned an invalid hypothesis") from exc
    support = result.supporting_evidence_ids
    conflict = result.conflicting_evidence_ids
    if (len(set(support)) != len(support) or len(set(conflict)) != len(conflict) or
            set(support) & set(conflict) or not set(support + conflict) <= lookup.keys()):
        raise ProviderOutputError("invalid_evidence_reference", "Evidence citation is outside this bundle")
    if result.cause_domain == CauseDomain.UNDETERMINED and not result.missing_evidence:
        raise ProviderOutputError("invalid_provider_output", "Reasoner returned an invalid hypothesis")
    if (not result.observed_behavioral_defect.strip() or not result.explanation.strip() or
            any(not entry.strip() or len(entry) > 4000 for entry in result.missing_evidence)):
        raise ProviderOutputError("invalid_provider_output", "Reasoner returned an invalid hypothesis")
    return {"observed_behavioral_defect": result.observed_behavioral_defect,
            "cause_domain": result.cause_domain.value,
            "performance_dimension": result.performance_dimension.value,
            "explanation": result.explanation,
            "supporting_evidence": [{"item_id": lookup[ref][0], "evaluation_id": lookup[ref][1]}
                                    for ref in support],
            "conflicting_evidence": [{"item_id": lookup[ref][0], "evaluation_id": lookup[ref][1]}
                                     for ref in conflict],
            "missing_evidence": result.missing_evidence,
            "provider_reported_confidence": result.provider_reported_confidence}


class BedrockReasoner:
    """Converse adapter. The public constructor always refuses remote invocation.

    A bound synthetic population or strict local workbook provenance is required. The real
    path rechecks the local bundle and prepares its own provider-safe projection. No API
    input or environment variable can self-assert that arbitrary evidence is safe.
    """

    def __init__(self, region: str = "us-east-1",
                 model_id: str = "global.anthropic.claude-sonnet-4-6", *, client=None):
        self.region = region
        self.model_id = model_id
        self._client = client
        self._synthetic_evaluation_ids: frozenset[str] | None = None
        self._trusted_evaluations: list[Evaluation] | None = None
        self._trusted_digest: str | None = None

    @classmethod
    def for_synthetic_evaluations(cls, region: str, model_id: str,
                                  evaluations: list[Evaluation], *, client=None) -> "BedrockReasoner":
        """Bind remote invocation to these synthetic records. Smoke entry point only.

        Never call this with ResultsCX normalized records or workbook output.
        """
        ids = frozenset(evaluation.internal_id for evaluation in evaluations)
        if not ids or len(ids) != len(evaluations):
            raise ValueError("Synthetic evaluations must be non-empty with unique internal IDs")
        reasoner = cls(region, model_id, client=client)
        reasoner._synthetic_evaluation_ids = ids
        return reasoner

    @classmethod
    def for_trusted_results_cx(cls, region: str, model_id: str, evaluations: list[Evaluation],
                               *, client=None) -> "BedrockReasoner":
        from app.results_cx.demo import TrustedResultsCXEvaluations

        if type(evaluations) is not TrustedResultsCXEvaluations or not evaluations:
            raise ValueError("Real remote diagnosis requires trusted local workbook provenance")
        evaluations.verify()
        reasoner = cls(region, model_id, client=client)
        # A private deep copy plus the loader's digest: later mutation of the caller's objects
        # cannot change what is sent, and in-place mutation of this copy is refused at use.
        reasoner._trusted_evaluations = [evaluation.model_copy(deep=True) for evaluation in evaluations]
        reasoner._trusted_digest = evaluations.content_digest
        return reasoner

    @property
    def remote_invocation_policy(self) -> str:
        """Read by `/diagnostics/mode` from the object; see `engine.remote_invocation_policy`."""
        if self._trusted_evaluations is not None:
            return "real_minimized"
        return "privacy_blocked" if self._synthetic_evaluation_ids is None else "synthetic_only"

    def _permits(self, bundle: ProviderEvidenceBundle) -> bool:
        allowed = self._synthetic_evaluation_ids
        if allowed is None:
            return False
        cited = {item.evaluation_id for item in bundle.items} | set(bundle.signal.affected_evaluation_ids)
        return bool(cited) and cited <= allowed and bundle.signal.total_evaluations == len(allowed)

    def _converse(self, payload: dict):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client(
                "bedrock-runtime", region_name=self.region,
                config=Config(connect_timeout=10, read_timeout=90,
                              retries={"max_attempts": 2, "mode": "standard"}))
        return self._client.converse(
            modelId=self.model_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": json.dumps(payload)}]}],
            inferenceConfig={"maxTokens": 1200, "temperature": 0},
        )

    def prepare_payload(self, evidence_bundle: ProviderEvidenceBundle) -> tuple[dict, dict]:
        if self._trusted_evaluations is not None:
            from .engine import build_bundle, detect_signals
            from .evidence_policy import population_digest, prepare_real_evidence

            evaluations = self._trusted_evaluations
            if population_digest(evaluations) != self._trusted_digest:
                raise ProviderOutputError("provider_privacy_blocked", "Remote diagnosis privacy policy blocked")
            signal = next((s for s in detect_signals(evaluations)
                           if s.signal_id == evidence_bundle.signal.signal_id), None)
            if signal is None:
                raise ProviderOutputError("provider_privacy_blocked", "Remote diagnosis privacy policy blocked")
            local = build_bundle(signal, evaluations)
            identities = {name for e in evaluations for name in (e.agent_name, e.qa_name, e.team_leader)}
            if local.provider_view(identities) != evidence_bundle:
                raise ProviderOutputError("provider_privacy_blocked", "Remote diagnosis privacy policy blocked")
            # Structured only in this milestone: no keyword is passed here, so the module
            # default decides and nothing outside this code path can turn real text on.
            prepared = prepare_real_evidence(local, evaluations)
            payload, lookup = prepared.payload, prepared.lookup
            validate_real_wire_payload(payload)
            if any("diagnostic_text" in item for item in payload["evidence_items"]):
                raise ProviderOutputError("provider_privacy_blocked", "Remote diagnosis privacy policy blocked")
        else:
            if not self._permits(evidence_bundle):
                raise ProviderOutputError("provider_privacy_blocked",
                                          "Remote diagnosis is disabled for non-synthetic evidence")
            payload, lookup = provider_safe_payload(evidence_bundle)
        return payload, lookup

    async def _diagnose_with_snapshot(self, evidence_bundle: ProviderEvidenceBundle) -> tuple[object, tuple[dict, dict]]:
        payload, lookup = self.prepare_payload(evidence_bundle)
        try:
            response = await asyncio.to_thread(self._converse, payload)
            # A truncated, filtered, or guardrail-stopped turn is refused even when its text
            # happens to parse; only a normally completed turn may become a hypothesis.
            if response.get("stopReason") != "end_turn":
                raise ProviderOutputError("invalid_provider_output", "Reasoner returned an invalid hypothesis")
            blocks = response["output"]["message"]["content"]
            if len(blocks) != 1 or set(blocks[0]) != {"text"}:
                raise ValueError("Unexpected Converse content")
            parsed = parse_response(blocks[0]["text"], lookup)
            request_id = response.get("ResponseMetadata", {}).get("RequestId")
            if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 128):
                request_id = None
        except ProviderOutputError:
            raise
        except Exception as exc:
            raise ProviderOutputError("reasoner_failure", "Reasoning provider failed") from exc
        # `generation_mode` is deliberately absent: the service stamps it from the object.
        result = {**parsed, "hypothesis_id": f"bedrock_{uuid4().hex}",
                  "signal_id": evidence_bundle.signal.signal_id,
                  "provider_metadata": {"provider": PROVIDER_NAME, "model": self.model_id,
                                        "invocation_region": self.region, "invocation_id": request_id,
                                        "generated_at": datetime.now(timezone.utc)}}
        return result, (payload, lookup)

    async def diagnose(self, evidence_bundle: ProviderEvidenceBundle) -> object:
        result, _ = await self._diagnose_with_snapshot(evidence_bundle)
        return result
