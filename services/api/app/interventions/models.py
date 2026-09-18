"""AWS-4 contracts. A proposed intervention and its solution review never change a diagnosis.

Lifecycle after M4 human validation:

    HUMAN VALIDATED -> INTERVENTION PROPOSED -> SOLUTION VALIDATED | SOLUTION QUESTIONED

The human-validated diagnosis is the authoritative input. The Intervention Reasoner proposes
what ResultsCX should do; the Solution Validator reviews whether that proposal addresses the
validated cause. Neither is a human decision. The AWS-3 semantic evidence review is carried
here as provenance only.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from app.design.models import DecisionType
from app.diagnostics.models import ApprovedDiagnosis, EvidenceReference, FrozenModel, ProviderMetadata


class InterventionType(StrEnum):
    """What ResultsCX should do. Five types; only the first two can lead to training design."""

    TRAINING = "training"
    PRACTICE_SIMULATION = "practice_simulation"
    COACHING = "coaching"
    PROCESS_CORRECTION = "process_correction"
    INVESTIGATE_FURTHER = "investigate_further"


# Deterministic projection onto the M5 `DecisionType` that the training orchestration consumes.
# It is a lifecycle mapping, not a cause-to-intervention rule: the reasoner chose the type.
M5_DECISION_TYPE = {
    InterventionType.TRAINING: DecisionType.TRAINING,
    InterventionType.PRACTICE_SIMULATION: DecisionType.TRAINING,
    InterventionType.COACHING: DecisionType.NON_TRAINING,
    InterventionType.PROCESS_CORRECTION: DecisionType.NON_TRAINING,
    InterventionType.INVESTIGATE_FURTHER: DecisionType.INVESTIGATE,
}
TRAINING_INTERVENTIONS = frozenset({InterventionType.TRAINING, InterventionType.PRACTICE_SIMULATION})


class SolutionAlignment(StrEnum):
    ALIGNED = "aligned"
    PARTIALLY_ALIGNED = "partially_aligned"
    MISALIGNED = "misaligned"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


SolutionStatus = Literal["solution_validated", "solution_questioned"]
InterventionStatus = Literal["intervention_proposed", "solution_validated", "solution_questioned"]
EvidenceReviewStatus = Literal["evidence_validated", "evidence_questioned", "not_reviewed",
                               "original_proposal_only"]
TrainingDesignGate = Literal["awaiting_solution_validation", "permitted", "withheld", "not_applicable"]


class SemanticReviewSummary(FrozenModel):
    """AWS-3 provenance carried downstream. It informs the audit trail; it approved nothing."""

    validation_id: str
    validation_outcome: str
    semantic_status: Literal["evidence_validated", "evidence_questioned"]
    assessed_proposal: Literal["provider_hypothesis"] = "provider_hypothesis"
    # False when the supervisor revised the diagnosis: the review described the original
    # proposal, not the diagnosis AWS-4 reasons from.
    describes_validated_diagnosis: bool


class InterventionProposal(FrozenModel):
    intervention_id: str
    hypothesis_id: str
    signal_id: str
    intervention_type: InterventionType
    recommendation: str
    rationale: str
    target_change: str
    fit_to_cause: str
    # Opaque wire references the reasoner cited, and the same references resolved locally.
    evidence_reference_ids: tuple[str, ...]
    evidence_refs: tuple[EvidenceReference, ...]
    limitations: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    # Self-reported by the provider. Not a calibrated probability.
    provider_reported_confidence: float
    # Locally stamped: provider, model, region, and generation mode come from the installed
    # object, never from the response.
    provider_metadata: ProviderMetadata
    created_at: datetime


class SolutionValidation(FrozenModel):
    solution_validation_id: str
    intervention_id: str
    hypothesis_id: str
    # The review always assesses the stored proposal against the human-validated diagnosis. It
    # never carries a diagnosis of its own.
    assessed: Literal["proposed_intervention"] = "proposed_intervention"
    alignment_outcome: SolutionAlignment
    solution_status: SolutionStatus
    alignment_assessment: str
    aligned_points: tuple[str, ...]
    misaligned_points: tuple[str, ...]
    unsupported_assumptions: tuple[str, ...]
    missing_information: tuple[str, ...]
    provider_reported_confidence: float
    provider_metadata: ProviderMetadata
    created_at: datetime


class DesignHandoff(FrozenModel):
    """The upstream decision AWS-5 consumes. Deterministic projection of the two records above.

    `training_design_gate` is a lifecycle gate, not an approval: `permitted` means the proposed
    intervention is a training or practice type and the solution review did not find it
    misaligned or undecidable. `withheld` means it is a training or practice type that the
    review questioned, so the training generator must not run on it. `not_applicable` covers
    coaching, process correction, and investigation, which never reach the training generator.
    No value here means a human approved the intervention.
    """

    hypothesis_id: str
    intervention_id: str
    solution_validation_id: str | None
    intervention_type: InterventionType
    decision_type: DecisionType
    solution_status: SolutionStatus | None
    training_design_gate: TrainingDesignGate
    human_reviewed_intervention: Literal[False] = False


class InterventionRecord(FrozenModel):
    """Process-local aggregate for one human-validated diagnosis. Replaced, never mutated."""

    hypothesis_id: str
    signal_id: str
    # Exactly which human-validated diagnosis was used, including the approval provenance.
    validated_diagnosis: ApprovedDiagnosis
    diagnosis_digest: str
    evidence_review_status: EvidenceReviewStatus
    semantic_review: SemanticReviewSummary | None
    status: InterventionStatus
    proposal: InterventionProposal
    solution_validation: SolutionValidation | None
    handoff: DesignHandoff
    created_at: datetime
    updated_at: datetime


def build_handoff(proposal: InterventionProposal, validation: SolutionValidation | None) -> DesignHandoff:
    kind = proposal.intervention_type
    if kind not in TRAINING_INTERVENTIONS:
        gate: TrainingDesignGate = "not_applicable"
    elif validation is None:
        gate = "awaiting_solution_validation"
    elif validation.alignment_outcome in (SolutionAlignment.ALIGNED, SolutionAlignment.PARTIALLY_ALIGNED):
        gate = "permitted"
    else:
        gate = "withheld"
    return DesignHandoff(hypothesis_id=proposal.hypothesis_id, intervention_id=proposal.intervention_id,
                         solution_validation_id=validation.solution_validation_id if validation else None,
                         intervention_type=kind, decision_type=M5_DECISION_TYPE[kind],
                         solution_status=validation.solution_status if validation else None,
                         training_design_gate=gate)


def solution_status_for(outcome: SolutionAlignment) -> SolutionStatus:
    return "solution_validated" if outcome == SolutionAlignment.ALIGNED else "solution_questioned"

