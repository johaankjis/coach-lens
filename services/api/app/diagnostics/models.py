"""M3 domain contracts. Facts, provider hypotheses, and human decisions stay separate."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.results_cx.models import Domain, SourceLineage


# Upper bounds on text accepted from the untrusted provider boundary and from reviewers.
# They are storage-safety limits, not content policy.
MAX_ID_LENGTH = 128
MAX_TEXT_LENGTH = 20_000
MAX_LIST_LENGTH = 200


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenModel(BaseModel):
    """Immutable value object. Audit content must not change after it is recorded."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PerformanceSignal(StrictModel):
    signal_id: str
    domain: Domain
    criterion: str
    evaluated_results: int = Field(ge=0)
    # Distinct evaluations that contain this criterion, and all evaluations in the loaded
    # dataset. They differ when a criterion is absent from some evaluations, so rates below
    # describe the represented evaluations only, never the whole dataset.
    evaluated_evaluations: int = Field(ge=0)
    total_evaluations: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    pass_rate: Decimal = Field(ge=0, le=1)
    fail_rate: Decimal = Field(ge=0, le=1)
    feedback_count: int = Field(ge=0)
    feedback_coverage: Decimal = Field(ge=0, le=1)
    max_score_total: Decimal = Field(ge=0)
    attained_score_total: Decimal = Field(ge=0)
    score_rate: Decimal = Field(ge=0, le=1)
    affected_evaluation_ids: list[str]
    source_lineages: list[SourceLineage] = Field(exclude=True)


class EvidenceItem(StrictModel):
    item_id: str
    evaluation_id: str
    domain: Domain
    criterion: str
    passed: bool
    answer: str
    max_score: Decimal
    attained_score: Decimal
    evaluator_feedback: str | None
    source_lineage: SourceLineage


class ProviderEvidenceItem(StrictModel):
    item_id: str
    evaluation_id: str
    domain: Domain
    criterion: str
    passed: bool
    answer: str
    max_score: Decimal
    attained_score: Decimal
    evaluator_feedback: str | None


class ProviderEvidenceBundle(StrictModel):
    signal: PerformanceSignal
    items: list[ProviderEvidenceItem]


REDACTED = "[redacted]"


def redact_known_identities(text: str, identity_terms: set[str]) -> str:
    """Replace whole-word, case-insensitive occurrences of known identity strings.

    This removes only the exact structured identity values already present in the
    canonical records (agent, evaluator, and leader names as recorded). It is not
    PII/PHI detection: partial names, nicknames, member or patient names, contact
    details, account numbers, addresses, and dates pass through unchanged.
    """
    terms = sorted((t.strip() for t in identity_terms if t and t.strip()), key=len, reverse=True)
    if not terms:
        return text
    alternatives = "|".join(r"\s+".join(re.escape(part) for part in term.split()) for term in terms)
    pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)
    return pattern.sub(REDACTED, text)


class EvidenceBundle(StrictModel):
    signal: PerformanceSignal
    items: list[EvidenceItem]

    def provider_view(self, identity_terms: set[str] | None = None) -> ProviderEvidenceBundle:
        """Remove source locations and known structured identity values before remote reasoning.

        See `redact_known_identities` for exactly what is and is not removed from feedback.
        """
        items = []
        for item in self.items:
            data = item.model_dump(exclude={"source_lineage"})
            if data["evaluator_feedback"]:
                data["evaluator_feedback"] = redact_known_identities(data["evaluator_feedback"],
                                                                     identity_terms or set())
            items.append(ProviderEvidenceItem.model_validate(data))
        return ProviderEvidenceBundle(signal=self.signal, items=items)


class CauseDomain(StrEnum):
    """ResultsCX Needs Analysis root-cause categories, plus an explicit unknown."""

    KNOWLEDGE_GAP = "knowledge_gap"
    SKILL_GAP = "skill_gap"
    PROCESS_GAP = "process_gap"
    UNDETERMINED = "undetermined"


class PerformanceDimension(StrEnum):
    """ISD skill-versus-will consideration, recorded separately from the cause domain.

    `capability`: the evidence suggests the agent could not perform the behavior as required.
    `execution`: the evidence suggests the agent could perform it but did not on the cited calls.
    `undetermined`: the evidence does not distinguish, or the question does not apply (for
    example when the cause domain is a process gap).
    These are descriptive labels for review; they assert nothing about intent or motivation.
    """

    CAPABILITY = "capability"
    EXECUTION = "execution"
    UNDETERMINED = "undetermined"


class EvidenceReference(FrozenModel):
    item_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    evaluation_id: str | None = Field(default=None, max_length=MAX_ID_LENGTH)


class ProviderMetadata(FrozenModel):
    provider: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    model: str | None = Field(default=None, max_length=MAX_ID_LENGTH)
    invocation_region: str | None = Field(default=None, max_length=MAX_ID_LENGTH,
                                          exclude_if=lambda value: value is None)
    invocation_id: str | None = Field(default=None, max_length=MAX_ID_LENGTH,
                                      exclude_if=lambda value: value is None)
    generated_at: datetime | None = Field(default=None, exclude_if=lambda value: value is None)
    generation_mode: Literal["provider", "controlled_fixture"] | None = Field(
        default=None, exclude_if=lambda value: value is None)


def _require_uncertainty_context(cause_domain: CauseDomain, missing_evidence: list[str], noun: str):
    if cause_domain == CauseDomain.UNDETERMINED and not missing_evidence:
        raise ValueError(f"undetermined {noun} requires missing evidence or unanswered questions")


class DiagnosticHypothesis(FrozenModel):
    """Provider interpretation. Lifecycle status lives on `DiagnosticRecord`, not here."""

    hypothesis_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    signal_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    observed_behavioral_defect: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    cause_domain: CauseDomain
    performance_dimension: PerformanceDimension
    explanation: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    supporting_evidence: list[EvidenceReference] = Field(min_length=1, max_length=MAX_LIST_LENGTH)
    conflicting_evidence: list[EvidenceReference] = Field(max_length=MAX_LIST_LENGTH)
    missing_evidence: list[str] = Field(max_length=MAX_LIST_LENGTH)
    # Self-reported by the provider. Not a calibrated probability and not derived from statistics.
    provider_reported_confidence: Decimal = Field(ge=0, le=1)
    provider_metadata: ProviderMetadata

    @model_validator(mode="after")
    def require_uncertainty_context(self):
        _require_uncertainty_context(self.cause_domain, self.missing_evidence, "diagnosis")
        if any(len(item) > MAX_TEXT_LENGTH for item in self.missing_evidence):
            raise ValueError("missing evidence entry is too long")
        return self


class HumanRevision(FrozenModel):
    observed_behavioral_defect: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    cause_domain: CauseDomain
    performance_dimension: PerformanceDimension
    explanation: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    supporting_evidence: list[EvidenceReference] = Field(min_length=1, max_length=MAX_LIST_LENGTH)
    conflicting_evidence: list[EvidenceReference] = Field(max_length=MAX_LIST_LENGTH)
    missing_evidence: list[str] = Field(max_length=MAX_LIST_LENGTH)

    @model_validator(mode="after")
    def require_uncertainty_context(self):
        _require_uncertainty_context(self.cause_domain, self.missing_evidence, "revision")
        if any(len(item) > MAX_TEXT_LENGTH for item in self.missing_evidence):
            raise ValueError("missing evidence entry is too long")
        return self


class ReviewEvent(FrozenModel):
    action: Literal["approve", "reject", "revise"]
    reviewer_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    occurred_at: datetime
    rationale: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    revision: HumanRevision | None = None


class DiagnosticRecord(StrictModel):
    """Lifecycle owner. `revised` plus `revision_approved` is the terminal state of a revision."""

    provider_hypothesis: DiagnosticHypothesis
    status: Literal["awaiting_review", "approved", "rejected", "revised"] = "awaiting_review"
    events: list[ReviewEvent] = Field(default_factory=list)
    human_revision: HumanRevision | None = None
    revision_approved: bool = False


class ApprovedDiagnosis(FrozenModel):
    hypothesis_id: str
    signal_id: str
    diagnosis: DiagnosticHypothesis | HumanRevision
    approved_by: str
    approved_at: datetime
    human_revised: bool
