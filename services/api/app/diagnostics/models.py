"""M3 domain contracts. Facts, provider hypotheses, and human decisions stay separate."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.results_cx.models import Domain, SourceLineage


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PerformanceSignal(StrictModel):
    signal_id: str
    domain: Domain
    criterion: str
    evaluated_results: int = Field(ge=0)
    evaluated_evaluations: int = Field(ge=0)
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


class EvidenceBundle(StrictModel):
    signal: PerformanceSignal
    items: list[EvidenceItem]

    def provider_view(self, identity_terms: set[str] | None = None) -> ProviderEvidenceBundle:
        """Remove source locations and known identity fields before remote reasoning."""
        terms = sorted((x for x in (identity_terms or set()) if x), key=len, reverse=True)
        items = []
        for item in self.items:
            data = item.model_dump(exclude={"source_lineage"})
            feedback = data["evaluator_feedback"]
            if feedback:
                for term in terms:
                    feedback = feedback.replace(term, "[redacted]")
                data["evaluator_feedback"] = feedback
            items.append(ProviderEvidenceItem.model_validate(data))
        return ProviderEvidenceBundle(signal=self.signal, items=items)


class CauseDomain(StrEnum):
    KNOWLEDGE_GAP = "knowledge_gap"
    SKILL_GAP = "skill_gap"
    PROCESS_GAP = "process_gap"
    UNDETERMINED = "undetermined"


class PerformanceDimension(StrEnum):
    CAPABILITY = "capability"
    EXECUTION = "execution"
    PROCESS_OR_SYSTEM = "process_or_system"
    UNDETERMINED = "undetermined"


class EvidenceReference(StrictModel):
    item_id: str = Field(min_length=1)
    evaluation_id: str | None = None


class ProviderMetadata(StrictModel):
    provider: str = Field(min_length=1)
    model: str | None = None


class DiagnosticHypothesis(StrictModel):
    hypothesis_id: str = Field(min_length=1)
    signal_id: str = Field(min_length=1)
    observed_behavioral_defect: str = Field(min_length=1)
    cause_domain: CauseDomain
    performance_dimension: PerformanceDimension
    explanation: str = Field(min_length=1)
    supporting_evidence: list[EvidenceReference] = Field(min_length=1)
    conflicting_evidence: list[EvidenceReference]
    missing_evidence: list[str]
    provider_reported_confidence: Decimal = Field(ge=0, le=1)
    provider_metadata: ProviderMetadata
    status: Literal["awaiting_review"] = "awaiting_review"

    @model_validator(mode="after")
    def require_uncertainty_context(self):
        if self.cause_domain == CauseDomain.UNDETERMINED and not self.missing_evidence:
            raise ValueError("undetermined diagnosis requires missing evidence or unanswered questions")
        return self


class HumanRevision(StrictModel):
    observed_behavioral_defect: str = Field(min_length=1)
    cause_domain: CauseDomain
    performance_dimension: PerformanceDimension
    explanation: str = Field(min_length=1)
    supporting_evidence: list[EvidenceReference] = Field(min_length=1)
    conflicting_evidence: list[EvidenceReference]
    missing_evidence: list[str]

    @model_validator(mode="after")
    def require_uncertainty_context(self):
        if self.cause_domain == CauseDomain.UNDETERMINED and not self.missing_evidence:
            raise ValueError("undetermined revision requires missing evidence or unanswered questions")
        return self


class ReviewEvent(StrictModel):
    action: Literal["approve", "reject", "revise"]
    reviewer_id: str = Field(min_length=1)
    occurred_at: datetime
    rationale: str | None = None
    revision: HumanRevision | None = None


class DiagnosticRecord(StrictModel):
    provider_hypothesis: DiagnosticHypothesis
    status: Literal["awaiting_review", "approved", "rejected", "revised"] = "awaiting_review"
    events: list[ReviewEvent] = Field(default_factory=list)
    human_revision: HumanRevision | None = None
    revision_approved: bool = False


class ApprovedDiagnosis(StrictModel):
    hypothesis_id: str
    signal_id: str
    diagnosis: DiagnosticHypothesis | HumanRevision
    approved_by: str
    approved_at: datetime
    human_revised: bool
