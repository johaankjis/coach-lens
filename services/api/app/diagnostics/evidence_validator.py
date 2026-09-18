"""Independent semantic review of one proposed diagnosis against its original wire evidence."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Literal, Protocol

from pydantic import Field, ValidationError, field_validator

from .bedrock import (PROVIDER_NAME, SIGNAL_PAYLOAD_KEYS, ITEM_PAYLOAD_KEYS,
                      provider_safe_payload,
                      TEXT_COVERAGE_KEYS, validate_real_wire_payload, _describe_type)
from .engine import (DiagnosticError, DiagnosticService, ProviderOutputError,
                     validate_citations, provider_kind)
from .models import FrozenModel, StrictModel, ProviderMetadata


class ValidationOutcome(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ValidatorResponse(StrictModel):
    validation_outcome: ValidationOutcome
    support_assessment: str = Field(min_length=1, max_length=4000)
    supported_reference_ids: list[str] = Field(max_length=100)
    contradicting_reference_ids: list[str] = Field(max_length=100)
    unsupported_claims: list[str] = Field(max_length=100)
    missing_evidence: list[str] = Field(max_length=100)
    provider_reported_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)

    @field_validator("support_assessment")
    @classmethod
    def nonblank_assessment(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("blank assessment")
        return value

    @field_validator("unsupported_claims", "missing_evidence")
    @classmethod
    def bounded_entries(cls, value: list[str]) -> list[str]:
        if any(not isinstance(entry, str) or not entry.strip() or len(entry) > 4000 for entry in value):
            raise ValueError("invalid list entry")
        return value


class EvidenceValidationRecord(FrozenModel):
    validation_id: str
    hypothesis_id: str
    signal_id: str
    validation_outcome: ValidationOutcome
    semantic_status: Literal["evidence_validated", "evidence_questioned"]
    support_assessment: str
    supported_reference_ids: tuple[str, ...]
    contradicting_reference_ids: tuple[str, ...]
    unsupported_claims: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    provider_reported_confidence: float
    provider_metadata: ProviderMetadata
    created_at: datetime


PROMPT = """You perform an independent evidence-based semantic review of the supplied proposed diagnosis.
Assess that proposal only. Never create a replacement diagnosis or cause_domain. Deterministic QA
statistics are authoritative. A recurring failure pattern proves what happened, not why.
Frequency or correlation alone does not establish knowledge, skill, process, coaching, or
training cause. Distinguish observation from causal inference. A diagnosis may be more
specific than the evidence permits. Check whether cited supporting evidence logically supports
each claim, whether cited conflicting evidence and uncited passing evidence weaken it, and
whether important gaps are acknowledged. Missing qualitative evidence matters. Real ResultsCX
evaluator comments may have been withheld by policy: absence of diagnostic_text does not mean
no local comment existed. Never invent or infer withheld comments. Reward a restrained
undetermined diagnosis when the evidence only proves an observed pattern. Use unsupported or
insufficient_evidence when appropriate. Confidence measures evidentiary support, not rhetoric.
Never assert human approval. Return exactly one JSON object, no markdown or surrounding prose."""


def response_contract() -> str:
    schema = ValidatorResponse.model_json_schema()
    lines = ["Exactly these required keys, with no extras:"]
    for name, prop in schema["properties"].items():
        if "$ref" in prop:
            prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[1]]
        lines.append(f'- "{name}": {_describe_type(prop)}')
    lines.append("All arrays remain JSON arrays, including single entries. Reference IDs must be copied "
                 "from the supplied evidence population without duplicates; a reference cannot be in both "
                 "reference lists. Confidence must be a JSON number, never a string or qualitative label. "
                 "Do not output IDs, provider/model metadata, timestamps, or a replacement diagnosis. "
                 "Malformed output is discarded without repair or retry.")
    return "\n".join(lines)


SYSTEM_PROMPT = PROMPT + "\n\n" + response_contract()
REQUEST_KEYS = frozenset({"signal", "evidence_items", "text_coverage", "proposed_diagnosis",
                          "citation_roles"})
PROPOSAL_KEYS = frozenset({"observed_behavioral_defect", "cause_domain",
                           "performance_dimension", "explanation", "missing_evidence",
                           "provider_reported_confidence"})
ROLE_KEYS = frozenset({"supporting_reference_ids", "conflicting_reference_ids"})
REF_PATTERN = re.compile(r"^(?:SIGNAL-001|EVID-\d{3,})$")


def parse_validator_response(text: str, allowed: set[str]) -> ValidatorResponse:
    try:
        raw = json.loads(text)
        confidence = raw.get("provider_reported_confidence") if isinstance(raw, dict) else None
        if type(confidence) not in (int, float):
            raise ValueError("non-numeric confidence")
        result = ValidatorResponse.model_validate(raw)
        refs = result.supported_reference_ids + result.contradicting_reference_ids
        if (any(not REF_PATTERN.fullmatch(ref) for ref in refs) or len(refs) != len(set(refs))
                or not set(refs) <= allowed):
            raise ValueError("invalid references")
        return result
    except (ValueError, TypeError, ValidationError, AttributeError) as exc:
        raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output") from exc


def _sensitive_diagnosis_text(diagnostics: DiagnosticService, texts: list[str]) -> bool:
    # A diagnosis is provider-authored text. Prevent known local identifiers from making a
    # second provider trip even if a fixture or compromised reasoner placed them in prose.
    terms = set()
    for evaluation in diagnostics.evaluations:
        terms.update((evaluation.internal_id, evaluation.agent_name, evaluation.qa_name,
                      evaluation.team_leader))
        for criterion in evaluation.criteria:
            terms.update((criterion.lineage.source_filename, criterion.lineage.source_sheet,
                          criterion.evaluator_feedback))
            # Arbitrary answer strings can contain free text. Common yes/no values are
            # too generic to screen without rejecting ordinary diagnosis prose.
            if len(criterion.answer.strip()) > 10:
                terms.add(criterion.answer)
    joined = "\n".join(texts).casefold()
    return (any(term and len(term.strip()) >= 3 and term.casefold() in joined for term in terms)
            or bool(re.search(r"\b(?:eval_|ev_|sig_)\w+|\b(?:source_lineage|source_filename|"
                              r"source_sheet|excel_row|filename)\b|\b(?:row|sheet|file|path)\s*[:#]?\s*\d+",
                              joined)))


def build_validation_request(diagnostics: DiagnosticService, hypothesis_id: str) -> tuple[dict, set[str]]:
    with diagnostics._lock:
        record = diagnostics._record(hypothesis_id)
        if record.status != "awaiting_review":
            raise DiagnosticError("invalid_state_transition", "Evidence review requires a proposed diagnosis")
        hypothesis = record.provider_hypothesis
        bundle = diagnostics._bundles[hypothesis_id]
        snapshot, lookup = deepcopy(diagnostics._provider_snapshots[hypothesis_id])
    if hypothesis.signal_id != bundle.signal.signal_id or bundle.signal.signal_id not in diagnostics.signals:
        raise DiagnosticError("evidence_mismatch", "Diagnosis and signal disagree")
    validate_citations(hypothesis.supporting_evidence, hypothesis.conflicting_evidence, bundle)
    # Rebuild local facts before using the saved provider-safe population.
    if diagnostics.evidence(hypothesis.signal_id) != bundle:
        raise DiagnosticError("evidence_mismatch", "Evidence population changed")
    if set(snapshot) not in ({"signal", "evidence_items"},
                             {"signal", "evidence_items", "text_coverage"}):
        raise DiagnosticError("invalid_provider_input", "Evidence projection is invalid")
    if "text_coverage" in snapshot:
        validate_real_wire_payload(snapshot)
        if any("diagnostic_text" in item for item in snapshot["evidence_items"]):
            raise DiagnosticError("provider_privacy_blocked", "Evidence privacy policy blocked")
        from .evidence_policy import prepare_real_evidence
        if snapshot != prepare_real_evidence(bundle, diagnostics.evaluations).payload:
            raise DiagnosticError("evidence_mismatch", "Evidence projection changed")
    elif (set(snapshot["signal"]) != SIGNAL_PAYLOAD_KEYS or
          any(set(item) != ITEM_PAYLOAD_KEYS for item in snapshot["evidence_items"])):
        raise DiagnosticError("invalid_provider_input", "Evidence projection is invalid")
    elif snapshot != provider_safe_payload(diagnostics.provider_evidence(hypothesis.signal_id))[0]:
        raise DiagnosticError("evidence_mismatch", "Evidence projection changed")
    expected_refs = {"SIGNAL-001"} | {f"EVID-{i:03d}" for i in range(1, len(bundle.items) + 1)}
    if set(lookup) != expected_refs or any(lookup[f"EVID-{number:03d}"] != (item.item_id, item.evaluation_id)
                                         for number, item in enumerate(bundle.items, 1)) \
            or lookup["SIGNAL-001"] != ("signal", None):
        raise DiagnosticError("evidence_mismatch", "Evidence reference mapping changed")
    reverse = {value: key for key, value in lookup.items()}
    supporting = [reverse[(ref.item_id, ref.evaluation_id)] for ref in hypothesis.supporting_evidence]
    conflicting = [reverse[(ref.item_id, ref.evaluation_id)] for ref in hypothesis.conflicting_evidence]
    proposal = {"observed_behavioral_defect": hypothesis.observed_behavioral_defect,
                "cause_domain": hypothesis.cause_domain.value,
                "performance_dimension": hypothesis.performance_dimension.value,
                "explanation": hypothesis.explanation,
                "missing_evidence": list(hypothesis.missing_evidence),
                "provider_reported_confidence": float(hypothesis.provider_reported_confidence)}
    if _sensitive_diagnosis_text(diagnostics, [proposal["observed_behavioral_defect"],
                                              proposal["explanation"], *proposal["missing_evidence"]]):
        raise DiagnosticError("provider_privacy_blocked", "Evidence privacy policy blocked")
    # Explicit allowlist: no model_dump of a local hypothesis or evidence object.
    request = {"signal": snapshot["signal"], "evidence_items": snapshot["evidence_items"],
               "text_coverage": snapshot.get("text_coverage", {"total_evidence_items": len(bundle.items),
                   "evidence_items_with_feedback": bundle.signal.feedback_count,
                   "minimized_text_items_allowed": 0,
                   "text_items_blocked": bundle.signal.feedback_count,
                   "text_items_with_no_text": len(bundle.items) - bundle.signal.feedback_count}),
               "proposed_diagnosis": proposal,
               "citation_roles": {"supporting_reference_ids": supporting,
                                  "conflicting_reference_ids": conflicting}}
    if (set(request) != REQUEST_KEYS or set(proposal) != PROPOSAL_KEYS or
            set(request["citation_roles"]) != ROLE_KEYS or
            set(request["text_coverage"]) != TEXT_COVERAGE_KEYS):
        raise DiagnosticError("invalid_provider_input", "Validation request projection drifted")
    return request, expected_refs


class SemanticEvidenceValidator(Protocol):
    async def validate(self, request: dict) -> object: ...


class UnavailableEvidenceValidator:
    async def validate(self, request: dict) -> object:
        raise DiagnosticError("validator_unavailable", "No evidence validator is configured")


class ControlledTestEvidenceValidator:
    controlled_fixture = True

    def __init__(self, response: object):
        self.response = response
        self.requests: list[dict] = []

    async def validate(self, request: dict) -> object:
        self.requests.append(deepcopy(request))
        return self.response


class BedrockEvidenceValidator:
    """Separate Converse invocation; only accepts a service-built allowlisted request."""

    def __init__(self, *, client=None):
        self.region = "us-east-1"
        self.model_id = "global.anthropic.claude-sonnet-4-6"
        self._client = client

    def _converse(self, request: dict):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("bedrock-runtime", region_name=self.region,
                                        config=Config(connect_timeout=10, read_timeout=90,
                                                      retries={"max_attempts": 2, "mode": "standard"}))
        return self._client.converse(modelId=self.model_id, system=[{"text": SYSTEM_PROMPT}],
                                    messages=[{"role": "user", "content": [{"text": json.dumps(request)}]}],
                                    inferenceConfig={"maxTokens": 1400, "temperature": 0})

    async def validate(self, request: dict) -> object:
        response = await asyncio.to_thread(self._converse, request)
        if response.get("stopReason") != "end_turn":
            raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output")
        try:
            blocks = response["output"]["message"]["content"]
            if len(blocks) != 1 or set(blocks[0]) != {"text"}:
                raise ValueError("Unexpected content")
            return blocks[0]["text"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output") from exc


class EvidenceValidationService:
    def __init__(self, diagnostics: DiagnosticService, validator: SemanticEvidenceValidator):
        self.diagnostics = diagnostics
        self.validator = validator
        self._records: dict[str, EvidenceValidationRecord] = {}
        self._lock = asyncio.Lock()

    def get(self, hypothesis_id: str) -> EvidenceValidationRecord:
        self.diagnostics.get(hypothesis_id)
        if hypothesis_id not in self._records:
            raise DiagnosticError("validation_not_found", "Evidence validation was not found")
        return self._records[hypothesis_id].model_copy(deep=True)

    async def run(self, hypothesis_id: str) -> EvidenceValidationRecord:
        async with self._lock:
            if hypothesis_id in self._records:
                return self.get(hypothesis_id)
            request, allowed = build_validation_request(self.diagnostics, hypothesis_id)
            if isinstance(self.validator, UnavailableEvidenceValidator):
                raise DiagnosticError("validator_unavailable", "No evidence validator is configured")
            if isinstance(self.validator, BedrockEvidenceValidator):
                from .bedrock import BedrockReasoner
                if (not isinstance(self.diagnostics.reasoner, BedrockReasoner) or
                        self.diagnostics.reasoner.remote_invocation_policy not in
                        ("synthetic_only", "real_minimized")):
                    raise DiagnosticError("provider_privacy_blocked", "Evidence privacy policy blocked")
            try:
                raw = await self.validator.validate(deepcopy(request))
                if isinstance(raw, str):
                    parsed = parse_validator_response(raw, allowed)
                else:
                    # Fixture adapters pass mappings through the same strict schema and ref checks.
                    parsed = parse_validator_response(json.dumps(raw), allowed)
            except ProviderOutputError as exc:
                raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output") from exc
            except Exception as exc:
                raise ProviderOutputError("validator_failure", "Evidence validator failed") from exc
            mode = "controlled_fixture" if provider_kind(self.validator) == "controlled_fixture" else "provider"
            metadata = (ProviderMetadata(provider=PROVIDER_NAME, model=self.validator.model_id,
                                         invocation_region=self.validator.region, generation_mode=mode)
                        if isinstance(self.validator, BedrockEvidenceValidator) else
                        ProviderMetadata(provider=("controlled fixture" if mode == "controlled_fixture"
                                                   else "external validator"), generation_mode=mode))
            # A human action may have happened while Converse was pending. Hold the same
            # lock as M4 transitions through the final state check and record commit.
            with self.diagnostics._lock:
                current = self.diagnostics._record(hypothesis_id)
                if current.status != "awaiting_review":
                    raise DiagnosticError("invalid_state_transition", "Evidence review requires a proposed diagnosis")
                result = EvidenceValidationRecord(
                    validation_id="val_" + sha256(hypothesis_id.encode()).hexdigest()[:24],
                    hypothesis_id=hypothesis_id, signal_id=current.provider_hypothesis.signal_id,
                    validation_outcome=parsed.validation_outcome,
                    semantic_status=("evidence_validated" if parsed.validation_outcome == ValidationOutcome.SUPPORTED
                                     else "evidence_questioned"),
                    support_assessment=parsed.support_assessment,
                    supported_reference_ids=tuple(parsed.supported_reference_ids),
                    contradicting_reference_ids=tuple(parsed.contradicting_reference_ids),
                    unsupported_claims=tuple(parsed.unsupported_claims), missing_evidence=tuple(parsed.missing_evidence),
                    provider_reported_confidence=parsed.provider_reported_confidence,
                    provider_metadata=metadata, created_at=datetime.now(timezone.utc))
                self._records[hypothesis_id] = result
            return result.model_copy(deep=True)
