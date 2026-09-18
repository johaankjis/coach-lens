"""Independent semantic review of one proposed diagnosis against its original wire evidence."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Callable, Literal, Protocol

from pydantic import Field, ValidationError, field_validator

from .bedrock import (PROVIDER_NAME, SIGNAL_PAYLOAD_KEYS, ITEM_PAYLOAD_KEYS,
                      provider_safe_payload,
                      TEXT_COVERAGE_KEYS, validate_real_wire_payload, _describe_type)
from .engine import (DiagnosticError, DiagnosticService, ProviderOutputError,
                     validate_citations, provider_kind)
from .models import EvidenceReference, FrozenModel, StrictModel, ProviderMetadata


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
    # The review always assesses the provider's original proposal. A later human revision is a
    # different diagnosis that this record says nothing about.
    assessed_proposal: Literal["provider_hypothesis"] = "provider_hypothesis"
    validation_outcome: ValidationOutcome
    semantic_status: Literal["evidence_validated", "evidence_questioned"]
    support_assessment: str
    supported_reference_ids: tuple[str, ...]
    contradicting_reference_ids: tuple[str, ...]
    # The same references resolved through the saved local lookup, so the review workspace
    # can open the exact evaluation rows the validator relied on or found contradictory.
    supported_evidence: tuple[EvidenceReference, ...]
    contradicting_evidence: tuple[EvidenceReference, ...]
    unsupported_claims: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    provider_reported_confidence: float
    provider_metadata: ProviderMetadata
    created_at: datetime


PROMPT = """You perform an independent semantic evidence review of one proposed diagnosis.
Answer only this question: does the supplied evidence support the proposed diagnosis? Assess
that proposal only. Never create, suggest, or imply a replacement diagnosis, cause_domain, or
performance_dimension, and never recommend training or coaching.

Input. CoachLens supplies deterministic QA facts that are authoritative; do not recalculate,
override, or reinterpret pass/fail results. Signal counts and rates describe only the criterion
results that were evaluated: evaluations_containing_criterion is how many evaluations contain
this criterion and total_loaded_evaluations is the whole loaded dataset, which may be larger.
evidence_items is the complete evidence population the Diagnostic Reasoner saw, including
items it did not cite. citation_roles lists which references the proposal cited as supporting
or conflicting. text_coverage reports qualitative evaluator feedback: evidence_items_with_feedback
and text_items_blocked count local evaluator comments that exist but were withheld from both the
reasoner and you by policy. Absence of feedback text never means no comment existed. Never
invent, guess, or paraphrase withheld comments, and treat any claim in the proposal about
evaluator statements, observations, or comments that were not supplied as unsupported.

Reasoning standard. A recurring failure pattern proves what happened, not why. Failure
frequency, failure rate, or score rate alone does not establish a knowledge, skill, process,
coaching, or training cause; a proposal that infers such a cause from counts alone makes a
claim stronger than the evidence permits. Distinguish the observed behavioral defect, which
structured facts can usually establish, from the causal claim (cause_domain,
performance_dimension, explanation), which structured facts alone usually cannot. Check whether
each cited supporting reference logically supports the claim it is cited for, whether cited
conflicting evidence and uncited passing evidence weaken a broad claim, and whether important
gaps are acknowledged in the proposal's missing_evidence. Missing qualitative evidence matters.
A restrained proposal that reports cause_domain "undetermined" with honest missing_evidence is
supported when the observed defect is backed by the evidence; do not penalize restraint.

Outcomes. supported: the observed defect and every causal claim are backed by the evidence and
nothing in the population materially contradicts them. partially_supported: the observed defect
is backed but the causal claim, confidence, or scope exceeds the evidence, or uncited evidence
weakens it. unsupported: the evidence contradicts the proposal or does not bear on its central
claim. insufficient_evidence: the supplied population cannot adjudicate the proposal either way,
typically because the distinguishing qualitative evidence is absent. Confidence measures how
strongly the evidence supports the proposal as written, not how persuasive its prose is. Never
assert or imply human approval; a human reviewer decides after this review. Return exactly one
JSON object, no markdown or surrounding prose."""

# Meaning of each response field. Types, enums, and bounds are rendered from the
# ValidatorResponse schema so the contract cannot drift from the parser.
FIELD_GUIDANCE = {
    "validation_outcome": "The single outcome defined above.",
    "support_assessment": "Plain-language reasoning for the outcome: which claims the evidence "
                          "establishes, which exceed it, and which references contradict it.",
    "supported_reference_ids": "References from the supplied population that actually support "
                               "the proposal, whether or not the proposal cited them. Must be "
                               "non-empty for supported and partially_supported.",
    "contradicting_reference_ids": "References from the supplied population that weaken or "
                                   "contradict the proposal, including uncited passing evidence. "
                                   "A reference cannot appear in both reference lists.",
    "unsupported_claims": "Claims the proposal makes that the evidence does not establish, "
                          "quoted or closely paraphrased. ALWAYS a JSON array of strings, "
                          "even for one claim; use [] when there are none. "
                          "unsupported requires at least one entry here or in "
                          "contradicting_reference_ids.",
    "missing_evidence": "Evidence that would be needed to establish or refute the causal claim. "
                        "ALWAYS a JSON array of strings, even for one item; use [] when "
                        "nothing is missing. Must be non-empty for "
                        "insufficient_evidence.",
    "provider_reported_confidence": "ALWAYS a JSON number literal such as 0.35, never a string. "
                                    "Qualitative labels such as \"low\", \"moderate\", \"high\", "
                                    "\"low_to_moderate\", and percentages such as \"35%\" are invalid.",
}

RESPONSE_SHAPE_EXAMPLE = {
    "validation_outcome": ValidationOutcome.SUPPORTED.value,
    "support_assessment": "The observed defect is supported; the cause remains undetermined.",
    "supported_reference_ids": ["SIGNAL-001"], "contradicting_reference_ids": [],
    "unsupported_claims": [], "missing_evidence": ["Direct workflow observation"],
    "provider_reported_confidence": 0.35,
}


def response_contract() -> str:
    schema = ValidatorResponse.model_json_schema()
    lines = ["Output contract. Return exactly one raw JSON object and nothing else: no markdown, "
             "no code fences, and no prose, labels, or comments before or after it. The object "
             "has exactly these seven keys, all required, and no other keys:"]
    for name, prop in schema["properties"].items():
        if "$ref" in prop:
            prop = schema["$defs"][prop["$ref"].rsplit("/", 1)[1]]
        lines.append(f'- "{name}": {_describe_type(prop)}. {FIELD_GUIDANCE[name]}')
    lines.append("All arrays remain JSON arrays, including single entries. Reference IDs must be copied "
                 "exactly from the supplied evidence population without duplicates. Confidence must be "
                 "a JSON number, never a string or qualitative label. Do not output local IDs, provider/model "
                 "metadata, timestamps, or a replacement diagnosis. Malformed or incoherent output is "
                 "discarded without repair or retry.")
    lines.append("Shape illustration with placeholder values (copy the types, not the values):")
    lines.append(json.dumps(RESPONSE_SHAPE_EXAMPLE))
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
        # An outcome must be grounded in the population: "supported" without a supporting
        # reference, "unsupported" without a named contradiction or unsupported claim, and
        # "insufficient" without a named gap are incoherent and are refused, not repaired.
        outcome = result.validation_outcome
        if ((outcome in (ValidationOutcome.SUPPORTED, ValidationOutcome.PARTIALLY_SUPPORTED)
             and not result.supported_reference_ids) or
                (outcome == ValidationOutcome.UNSUPPORTED and not result.unsupported_claims
                 and not result.contradicting_reference_ids) or
                (outcome == ValidationOutcome.INSUFFICIENT_EVIDENCE and not result.missing_evidence)):
            raise ValueError("incoherent outcome")
        return result
    except (ValueError, TypeError, ValidationError, AttributeError) as exc:
        raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output") from exc


MIN_IDENTIFIER_LENGTH = 3
# Structured-only reasoning never sees comments, so only a long verbatim match indicates a
# leak; short comments such as "Missed greeting" are ordinary diagnostic prose.
MIN_FREE_TEXT_LENGTH = 20
_LOCAL_ID_PATTERN = re.compile(r"\b(?:eval_|ev_|sig_)\w+|\b(?:source_lineage|source_filename|"
                               r"source_sheet|excel_row|filename)\b|\b(?:row|sheet|file|path)\s*[:#]?\s*\d+")


def _sensitive_diagnosis_text(diagnostics: DiagnosticService, texts: list[str]) -> bool:
    # A diagnosis is provider-authored text. Prevent known local identifiers from making a
    # second provider trip even if a fixture or compromised reasoner placed them in prose.
    identifiers = set()
    free_text = set()
    for evaluation in diagnostics.evaluations:
        identifiers.update((evaluation.internal_id, evaluation.agent_name, evaluation.qa_name,
                            evaluation.team_leader))
        for criterion in evaluation.criteria:
            identifiers.update((criterion.lineage.source_filename, criterion.lineage.source_sheet))
            free_text.update((criterion.evaluator_feedback, criterion.answer))
    joined = "\n".join(texts).casefold()
    # Identifiers match as whole words (as `redact_known_identities` does) so that a name such
    # as "Ana" or a sheet called "QA" does not block prose containing "analysis" or "QA rows".
    identifier_terms = [term.strip() for term in identifiers if term and len(term.strip()) >= MIN_IDENTIFIER_LENGTH]
    if identifier_terms:
        alternatives = "|".join(r"\s+".join(re.escape(part) for part in term.split()) for term in identifier_terms)
        if re.search(rf"(?<!\w)(?:{alternatives})(?!\w)", joined, re.IGNORECASE):
            return True
    if any(term and len(term.strip()) >= MIN_FREE_TEXT_LENGTH and term.strip().casefold() in joined
           for term in free_text):
        return True
    return bool(_LOCAL_ID_PATTERN.search(joined))


def load_provider_population(diagnostics: DiagnosticService, hypothesis_id: str):
    """Re-verify and return the exact provider-safe population saved for one hypothesis.

    Shared by AWS-3 and AWS-4: local facts are rebuilt and compared with the stored bundle,
    the saved allowlisted projection is compared with a fresh projection, and the opaque
    reference lookup is checked against the bundle. Returns the stored record (live object,
    read-only by convention), the bundle, a deep copy of the wire snapshot, a deep copy of
    the local lookup, and the set of references that exist in the population.
    """
    with diagnostics._lock:
        record = diagnostics._record(hypothesis_id)
        hypothesis = record.provider_hypothesis
        bundle = diagnostics._bundles[hypothesis_id]
        snapshot, lookup = deepcopy(diagnostics._provider_snapshots[hypothesis_id])
    if hypothesis.signal_id != bundle.signal.signal_id or bundle.signal.signal_id not in diagnostics.signals:
        raise DiagnosticError("evidence_mismatch", "Diagnosis and signal disagree")
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
    return record, bundle, snapshot, lookup, expected_refs


def default_text_coverage(bundle) -> dict:
    """Coverage for a synthetic snapshot that carried none: every local comment was withheld."""
    return {"total_evidence_items": len(bundle.items),
            "evidence_items_with_feedback": bundle.signal.feedback_count,
            "minimized_text_items_allowed": 0,
            "text_items_blocked": bundle.signal.feedback_count,
            "text_items_with_no_text": len(bundle.items) - bundle.signal.feedback_count}


def build_validation_request(diagnostics: DiagnosticService, hypothesis_id: str) -> tuple[dict, set[str], dict]:
    with diagnostics._lock:
        record = diagnostics._record(hypothesis_id)
        if record.status != "awaiting_review":
            raise DiagnosticError("invalid_state_transition", "Evidence review requires a proposed diagnosis")
        hypothesis = record.provider_hypothesis
    _, bundle, snapshot, lookup, expected_refs = load_provider_population(diagnostics, hypothesis_id)
    validate_citations(hypothesis.supporting_evidence, hypothesis.conflicting_evidence, bundle)
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
               "text_coverage": snapshot.get("text_coverage", default_text_coverage(bundle)),
               "proposed_diagnosis": proposal,
               "citation_roles": {"supporting_reference_ids": supporting,
                                  "conflicting_reference_ids": conflicting}}
    if (set(request) != REQUEST_KEYS or set(proposal) != PROPOSAL_KEYS or
            set(request["citation_roles"]) != ROLE_KEYS or
            set(request["text_coverage"]) != TEXT_COVERAGE_KEYS):
        raise DiagnosticError("invalid_provider_input", "Validation request projection drifted")
    return request, expected_refs, lookup


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

    def __init__(self, region: str = "us-east-1",
                 model_id: str = "global.anthropic.claude-sonnet-4-6", *, client=None,
                 diagnostic_sink: Callable[[dict], None] | None = None):
        self.region = region
        self.model_id = model_id
        self._client = client
        # Only the synthetic smoke supplies a sink. No provider text or request data is sent.
        self._diagnostic_sink = diagnostic_sink

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
        if self._diagnostic_sink is not None:
            self._diagnostic_sink(describe_validator_converse(response))
        if response.get("stopReason") != "end_turn":
            raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output")
        try:
            blocks = response["output"]["message"]["content"]
            if not isinstance(blocks, list):
                raise ValueError("Unexpected content")
            texts = []
            for block in blocks:
                if not isinstance(block, dict) or len(block) != 1:
                    raise ValueError("Unexpected content")
                if "text" in block and isinstance(block["text"], str):
                    texts.append(block["text"])
                elif "reasoningContent" not in block:
                    raise ValueError("Unexpected content")
            if not texts or not any(text.strip() for text in texts):
                raise ValueError("Empty content")
            return "".join(texts)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderOutputError("invalid_validator_output", "Validator returned invalid output") from exc


def describe_validator_converse(response: object) -> dict:
    """Smoke-only response shape and JSON syntax, without model text or AWS metadata."""
    if not isinstance(response, dict):
        return {"response_shape": "non_object"}
    stop = response.get("stopReason")
    known_stops = {"end_turn", "max_tokens", "tool_use", "stop_sequence", "guardrail_intervened",
                   "content_filtered", "malformed_model_output", "malformed_tool_use",
                   "model_context_window_exceeded"}
    output = response.get("output")
    message = output.get("message") if isinstance(output, dict) else None
    blocks = message.get("content") if isinstance(message, dict) else None
    diagnostic = {"stop_reason": stop if isinstance(stop, str) and stop in known_stops else "other",
                  "content_shape": "non_array" if not isinstance(blocks, list) else
                                   [next(iter(block)) if isinstance(block, dict) and len(block) == 1 and
                                    next(iter(block)) in {"text", "reasoningContent", "toolUse"} else "other"
                                    for block in blocks]}
    if not isinstance(blocks, list):
        return diagnostic
    texts = [block["text"] for block in blocks if isinstance(block, dict) and
             set(block) == {"text"} and isinstance(block["text"], str)]
    payload = "".join(texts)
    diagnostic["text_lengths"] = [len(value) for value in texts]
    first = payload.lstrip()
    diagnostic["text_envelope"] = ("empty" if not first else "markdown_fence" if first.startswith("```")
                                   else "json_object_start" if first.startswith("{") else
                                   "json_array_start" if first.startswith("[") else "prose_or_other")
    try:
        json.loads(payload)
        diagnostic["json_syntax"] = "valid"
    except json.JSONDecodeError as exc:
        diagnostic["json_syntax"] = "invalid"
        diagnostic["json_error_position"] = exc.pos
    return diagnostic


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
            request, allowed, lookup = build_validation_request(self.diagnostics, hypothesis_id)
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
                resolve = lambda refs: tuple(EvidenceReference(item_id=lookup[ref][0],  # noqa: E731
                                                               evaluation_id=lookup[ref][1]) for ref in refs)
                result = EvidenceValidationRecord(
                    validation_id="val_" + sha256(hypothesis_id.encode()).hexdigest()[:24],
                    hypothesis_id=hypothesis_id, signal_id=current.provider_hypothesis.signal_id,
                    validation_outcome=parsed.validation_outcome,
                    semantic_status=("evidence_validated" if parsed.validation_outcome == ValidationOutcome.SUPPORTED
                                     else "evidence_questioned"),
                    support_assessment=parsed.support_assessment,
                    supported_reference_ids=tuple(parsed.supported_reference_ids),
                    contradicting_reference_ids=tuple(parsed.contradicting_reference_ids),
                    supported_evidence=resolve(parsed.supported_reference_ids),
                    contradicting_evidence=resolve(parsed.contradicting_reference_ids),
                    unsupported_claims=tuple(parsed.unsupported_claims), missing_evidence=tuple(parsed.missing_evidence),
                    provider_reported_confidence=parsed.provider_reported_confidence,
                    provider_metadata=metadata, created_at=datetime.now(timezone.utc))
                self._records[hypothesis_id] = result
            return result.model_copy(deep=True)
