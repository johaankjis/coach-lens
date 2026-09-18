"""Orchestration from the M3 approval gate to immutable AWS-4 records.

Two explicit stages share one lock: `propose` (Intervention Reasoner) and `validate_solution`
(Solution Validator). Both re-run the human-approval gate, rebuild and re-verify the exact
provider-safe evidence population saved for the diagnosis, and refuse to send anything the
allowlist does not name. Neither stage can change the diagnosis, and a repeat request returns
the stored record without another provider call.
"""

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Protocol

from app.diagnostics.engine import DiagnosticError, DiagnosticService, validate_citations
from app.diagnostics.evidence_validator import (TEXT_COVERAGE_KEYS, EvidenceValidationService,
                                                 _sensitive_diagnosis_text, default_text_coverage,
                                                 load_provider_population)
from app.diagnostics.models import ApprovedDiagnosis, EvidenceReference, ProviderMetadata

from .bedrock import (PROVIDER_NAME, BedrockInterventionReasoner, BedrockSolutionValidator,
                      InterventionError, InterventionOutputError, parse_intervention_response,
                      parse_solution_response)
from .models import (InterventionProposal, InterventionRecord, SemanticReviewSummary,
                     SolutionValidation, build_handoff, solution_status_for)


REQUEST_KEYS = frozenset({"signal", "evidence_items", "text_coverage", "validated_diagnosis",
                          "citation_roles", "human_validation"})
DIAGNOSIS_KEYS = frozenset({"observed_behavioral_defect", "cause_domain", "performance_dimension",
                            "explanation", "missing_evidence"})
ROLE_KEYS = frozenset({"supporting_reference_ids", "conflicting_reference_ids"})
HUMAN_VALIDATION_KEYS = frozenset({"human_revised", "revision_rationale"})
SOLUTION_REQUEST_KEYS = REQUEST_KEYS | {"proposed_intervention"}
PROPOSED_KEYS = frozenset({"intervention_type", "recommendation", "rationale", "target_change",
                           "fit_to_cause", "evidence_reference_ids", "limitations", "missing_evidence",
                           "provider_reported_confidence"})

# Codes and the only message text that may reach a client for each. Anything else a provider
# raises is reported as a generic failure so provider-authored text never reaches a response.
ERROR_MESSAGES = {
    "intervention_provider_unavailable": "No intervention reasoner is configured",
    "solution_validator_unavailable": "No solution validator is configured",
    "invalid_intervention_output": "Intervention reasoner returned invalid output",
    "intervention_provider_failure": "Intervention reasoner failed",
    "invalid_solution_output": "Solution validator returned invalid output",
    "solution_validator_failure": "Solution validator failed",
    "intervention_not_found": "No intervention has been proposed for this diagnosis",
    "intervention_stale": "The stored intervention does not match the current validated diagnosis",
    "provider_privacy_blocked": "Remote intervention privacy policy blocked",
}


class InterventionReasonerProvider(Protocol):
    async def propose(self, request: dict) -> object: ...


class SolutionValidatorProvider(Protocol):
    async def validate(self, request: dict) -> object: ...


class UnavailableInterventionReasoner:
    async def propose(self, request: dict) -> object:
        raise InterventionError("intervention_provider_unavailable", ERROR_MESSAGES["intervention_provider_unavailable"])


class UnavailableSolutionValidator:
    async def validate(self, request: dict) -> object:
        raise InterventionError("solution_validator_unavailable", ERROR_MESSAGES["solution_validator_unavailable"])


class ControlledInterventionReasoner:
    """Test and demo double: returns the supplied response verbatim. Performs no inference."""

    controlled_fixture = True

    def __init__(self, response: object):
        self.response = response
        self.requests: list[dict] = []

    async def propose(self, request: dict) -> object:
        self.requests.append(deepcopy(request))
        return self.response


class ControlledSolutionValidator:
    controlled_fixture = True

    def __init__(self, response: object):
        self.response = response
        self.requests: list[dict] = []

    async def validate(self, request: dict) -> object:
        self.requests.append(deepcopy(request))
        return self.response


def intervention_provider_kind(provider: object) -> str:
    """Classify an installed object from the object, never from a label."""
    if isinstance(provider, (UnavailableInterventionReasoner, UnavailableSolutionValidator)):
        return "unavailable"
    if getattr(provider, "controlled_fixture", False) is True:
        return "controlled_fixture"
    return "provider"


def diagnosis_digest(approved: ApprovedDiagnosis) -> str:
    canonical = json.dumps(approved.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InterventionContext:
    approved: ApprovedDiagnosis
    request: dict
    allowed_refs: frozenset[str]
    lookup: dict[str, tuple[str, str | None]]


def build_intervention_context(diagnostics: DiagnosticService, hypothesis_id: str) -> InterventionContext:
    """Gate, re-verify the saved provider-safe population, and project the validated diagnosis.

    The reviewer identifier never enters the request. Diagnostic prose and the reviewer's
    revision rationale are screened against known local identifiers and comments before any
    provider trip, as AWS-3 does for provider prose. This is a narrow screen, not PHI detection.
    """
    approved = diagnostics.get_approved_diagnosis(hypothesis_id)
    _, bundle, snapshot, lookup, _ = load_provider_population(diagnostics, hypothesis_id)
    diagnosis = approved.diagnosis
    validate_citations(diagnosis.supporting_evidence, diagnosis.conflicting_evidence, bundle)
    reverse = {value: key for key, value in lookup.items()}
    supporting = [reverse[(ref.item_id, ref.evaluation_id)] for ref in diagnosis.supporting_evidence]
    conflicting = [reverse[(ref.item_id, ref.evaluation_id)] for ref in diagnosis.conflicting_evidence]
    revision_rationale = None
    if approved.human_revised:
        record = diagnostics.get(hypothesis_id)
        revision_rationale = next((event.rationale for event in record.events if event.action == "revise"), None)
    texts = [diagnosis.observed_behavioral_defect, diagnosis.explanation, *diagnosis.missing_evidence]
    if revision_rationale:
        texts.append(revision_rationale)
    if _sensitive_diagnosis_text(diagnostics, texts):
        raise DiagnosticError("provider_privacy_blocked", "Evidence privacy policy blocked")
    # Explicit allowlist: no model_dump of a local diagnosis or evidence object.
    request = {"signal": snapshot["signal"], "evidence_items": snapshot["evidence_items"],
               "text_coverage": snapshot.get("text_coverage", default_text_coverage(bundle)),
               "validated_diagnosis": {"observed_behavioral_defect": diagnosis.observed_behavioral_defect,
                                       "cause_domain": diagnosis.cause_domain.value,
                                       "performance_dimension": diagnosis.performance_dimension.value,
                                       "explanation": diagnosis.explanation,
                                       "missing_evidence": list(diagnosis.missing_evidence)},
               "citation_roles": {"supporting_reference_ids": supporting,
                                  "conflicting_reference_ids": conflicting},
               "human_validation": {"human_revised": approved.human_revised,
                                    "revision_rationale": revision_rationale}}
    if (set(request) != REQUEST_KEYS or set(request["validated_diagnosis"]) != DIAGNOSIS_KEYS or
            set(request["citation_roles"]) != ROLE_KEYS or set(request["text_coverage"]) != TEXT_COVERAGE_KEYS or
            set(request["human_validation"]) != HUMAN_VALIDATION_KEYS):
        raise DiagnosticError("invalid_provider_input", "Intervention request projection drifted")
    return InterventionContext(approved=approved, request=request,
                               allowed_refs=frozenset(supporting + conflicting), lookup=lookup)


def _bedrock_permitted(diagnostics: DiagnosticService) -> bool:
    """A remote AWS-4 call is only permitted for a diagnosis whose evidence already crossed
    through a bound synthetic or trusted ResultsCX Bedrock reasoner (the AWS-2/AWS-3 gate)."""
    from app.diagnostics.bedrock import BedrockReasoner
    reasoner = diagnostics.reasoner
    return isinstance(reasoner, BedrockReasoner) and reasoner.remote_invocation_policy in (
        "synthetic_only", "real_minimized")


def _metadata(provider: object, bedrock_type: type) -> ProviderMetadata:
    mode = "controlled_fixture" if intervention_provider_kind(provider) == "controlled_fixture" else "provider"
    if isinstance(provider, bedrock_type):
        return ProviderMetadata(provider=PROVIDER_NAME, model=provider.model_id,
                                invocation_region=provider.region, generated_at=datetime.now(timezone.utc),
                                generation_mode=mode)
    return ProviderMetadata(provider="controlled fixture" if mode == "controlled_fixture" else "external provider",
                            generated_at=datetime.now(timezone.utc), generation_mode=mode)


class InterventionService:
    def __init__(self, diagnostics: DiagnosticService, evidence_validations: EvidenceValidationService | None,
                 reasoner: InterventionReasonerProvider, validator: SolutionValidatorProvider):
        self.diagnostics = diagnostics
        self.evidence_validations = evidence_validations
        self.reasoner = reasoner
        self.validator = validator
        self._records: dict[str, InterventionRecord] = {}
        self._lock = asyncio.Lock()

    def get(self, hypothesis_id: str) -> InterventionRecord:
        approved = self.diagnostics.get_approved_diagnosis(hypothesis_id)  # Gate on reads too.
        record = self._records.get(hypothesis_id)
        if record is None:
            raise InterventionError("intervention_not_found", ERROR_MESSAGES["intervention_not_found"])
        if record.diagnosis_digest != diagnosis_digest(approved):
            raise InterventionError("intervention_stale", ERROR_MESSAGES["intervention_stale"])
        return record.model_copy(deep=True)

    def _semantic_review(self, hypothesis_id: str, human_revised: bool) -> tuple[SemanticReviewSummary | None, str]:
        if self.evidence_validations is None:
            return None, "not_reviewed"
        try:
            review = self.evidence_validations.get(hypothesis_id)
        except DiagnosticError as exc:
            if exc.code != "validation_not_found":
                raise
            return None, "not_reviewed"
        summary = SemanticReviewSummary(validation_id=review.validation_id,
                                        validation_outcome=review.validation_outcome.value,
                                        semantic_status=review.semantic_status,
                                        describes_validated_diagnosis=not human_revised)
        return summary, ("original_proposal_only" if human_revised else review.semantic_status)

    async def _invoke(self, call, request: dict, output_code: str, failure_code: str) -> str:
        try:
            raw = await call(deepcopy(request))
        except InterventionError as exc:
            if exc.code in ("intervention_provider_unavailable", "solution_validator_unavailable"):
                raise InterventionError(exc.code, ERROR_MESSAGES[exc.code]) from exc
            code = output_code if isinstance(exc, InterventionOutputError) else failure_code
            raise InterventionOutputError(code, ERROR_MESSAGES[code]) from exc
        except Exception as exc:
            raise InterventionOutputError(failure_code, ERROR_MESSAGES[failure_code]) from exc
        if isinstance(raw, str):
            return raw
        # Fixture adapters pass mappings through the same strict parser as model text.
        try:
            return json.dumps(raw)
        except (TypeError, ValueError) as exc:
            raise InterventionOutputError(output_code, ERROR_MESSAGES[output_code]) from exc

    async def propose(self, hypothesis_id: str) -> InterventionRecord:
        async with self._lock:
            if hypothesis_id in self._records:
                return self.get(hypothesis_id)
            context = build_intervention_context(self.diagnostics, hypothesis_id)
            if isinstance(self.reasoner, UnavailableInterventionReasoner):
                raise InterventionError("intervention_provider_unavailable",
                                        ERROR_MESSAGES["intervention_provider_unavailable"])
            if isinstance(self.reasoner, BedrockInterventionReasoner) and not _bedrock_permitted(self.diagnostics):
                raise InterventionError("provider_privacy_blocked", ERROR_MESSAGES["provider_privacy_blocked"])
            text = await self._invoke(self.reasoner.propose, context.request,
                                      "invalid_intervention_output", "intervention_provider_failure")
            parsed = parse_intervention_response(text, set(context.allowed_refs))
            approved = context.approved
            # The approval is terminal in M3, but re-read it after the provider call anyway so
            # the record can never describe a diagnosis other than the one currently approved.
            if diagnosis_digest(self.diagnostics.get_approved_diagnosis(hypothesis_id)) != diagnosis_digest(approved):
                raise InterventionError("intervention_stale", ERROR_MESSAGES["intervention_stale"])
            now = datetime.now(timezone.utc)
            intervention_id = "int_" + sha256(f"{hypothesis_id}:{approved.approved_at.isoformat()}".encode()).hexdigest()[:24]
            proposal = InterventionProposal(
                intervention_id=intervention_id, hypothesis_id=hypothesis_id, signal_id=approved.signal_id,
                intervention_type=parsed.intervention_type, recommendation=parsed.recommendation,
                rationale=parsed.rationale, target_change=parsed.target_change, fit_to_cause=parsed.fit_to_cause,
                evidence_reference_ids=tuple(parsed.evidence_reference_ids),
                evidence_refs=tuple(EvidenceReference(item_id=context.lookup[ref][0],
                                                      evaluation_id=context.lookup[ref][1])
                                    for ref in parsed.evidence_reference_ids),
                limitations=tuple(parsed.limitations), missing_evidence=tuple(parsed.missing_evidence),
                provider_reported_confidence=parsed.provider_reported_confidence,
                provider_metadata=_metadata(self.reasoner, BedrockInterventionReasoner), created_at=now)
            semantic, review_status = self._semantic_review(hypothesis_id, approved.human_revised)
            record = InterventionRecord(
                hypothesis_id=hypothesis_id, signal_id=approved.signal_id, validated_diagnosis=approved,
                diagnosis_digest=diagnosis_digest(approved), evidence_review_status=review_status,
                semantic_review=semantic, status="intervention_proposed", proposal=proposal,
                solution_validation=None, handoff=build_handoff(proposal, None), created_at=now, updated_at=now)
            self._records[hypothesis_id] = record
            return record.model_copy(deep=True)

    async def validate_solution(self, hypothesis_id: str) -> InterventionRecord:
        async with self._lock:
            record = self.get(hypothesis_id)
            if record.solution_validation is not None:
                return record
            # Rebuild and re-verify the same population and diagnosis the proposal used.
            context = build_intervention_context(self.diagnostics, hypothesis_id)
            if diagnosis_digest(context.approved) != record.diagnosis_digest:
                raise InterventionError("intervention_stale", ERROR_MESSAGES["intervention_stale"])
            if isinstance(self.validator, UnavailableSolutionValidator):
                raise InterventionError("solution_validator_unavailable",
                                        ERROR_MESSAGES["solution_validator_unavailable"])
            if isinstance(self.validator, BedrockSolutionValidator) and not _bedrock_permitted(self.diagnostics):
                raise InterventionError("provider_privacy_blocked", ERROR_MESSAGES["provider_privacy_blocked"])
            proposal = record.proposal
            proposed = {"intervention_type": proposal.intervention_type.value,
                        "recommendation": proposal.recommendation, "rationale": proposal.rationale,
                        "target_change": proposal.target_change, "fit_to_cause": proposal.fit_to_cause,
                        "evidence_reference_ids": list(proposal.evidence_reference_ids),
                        "limitations": list(proposal.limitations),
                        "missing_evidence": list(proposal.missing_evidence),
                        "provider_reported_confidence": proposal.provider_reported_confidence}
            request = {**context.request, "proposed_intervention": proposed}
            if set(request) != SOLUTION_REQUEST_KEYS or set(proposed) != PROPOSED_KEYS:
                raise DiagnosticError("invalid_provider_input", "Solution request projection drifted")
            text = await self._invoke(self.validator.validate, request,
                                      "invalid_solution_output", "solution_validator_failure")
            parsed = parse_solution_response(text)
            now = datetime.now(timezone.utc)
            validation = SolutionValidation(
                solution_validation_id="sol_" + sha256(proposal.intervention_id.encode()).hexdigest()[:24],
                intervention_id=proposal.intervention_id, hypothesis_id=hypothesis_id,
                alignment_outcome=parsed.alignment_outcome,
                solution_status=solution_status_for(parsed.alignment_outcome),
                alignment_assessment=parsed.alignment_assessment,
                aligned_points=tuple(parsed.aligned_points), misaligned_points=tuple(parsed.misaligned_points),
                unsupported_assumptions=tuple(parsed.unsupported_assumptions),
                missing_information=tuple(parsed.missing_information),
                provider_reported_confidence=parsed.provider_reported_confidence,
                provider_metadata=_metadata(self.validator, BedrockSolutionValidator), created_at=now)
            updated = record.model_copy(update={
                "solution_validation": validation, "status": validation.solution_status,
                "handoff": build_handoff(proposal, validation), "updated_at": now}, deep=True)
            self._records[hypothesis_id] = updated
            return updated.model_copy(deep=True)
