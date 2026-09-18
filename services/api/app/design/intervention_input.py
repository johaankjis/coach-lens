"""The narrow input boundary between AWS-4 solution validation and AWS-5 training design.

`ValidatedTrainingIntervention` is the only thing the Training Designer designs from. It is
built from the M5 `InterventionDecision` that the AWS-4 handoff projected from the stored
intervention record, plus the human-approved diagnosis. AWS-4 is authoritative for whether
training design may proceed: the decision must name a `training` or `practice_simulation`
intervention, an `aligned` solution outcome, a `permitted` gate, and the AWS-4 identifiers.
No cause-to-intervention rule lives here. The approved cause only shapes what the package
emphasizes (`training_focus`); it never decides eligibility.

Refusals are fixed identifiers whose messages come from `service.REFUSAL_MESSAGES`, so
nothing typed by a provider or reviewer reaches a client through a refusal.
"""

from typing import Literal

from pydantic import Field

from app.diagnostics.models import CauseDomain, EvidenceReference, FrozenModel, PerformanceDimension

from .models import (AWS4_VALIDATION_SOURCE, DecisionType, DesignId, DesignInput, DesignText,
                     InterventionDecision, MAX_ITEMS, TRAINING_INTERVENTION_TYPES, TrainingFocus)
from .service import TrainingDesignRefused, training_design_permitted


ValidationSource = Literal["aws4_solution_validator"]


def training_focus_for(intervention_type: str, cause_domain: CauseDomain) -> TrainingFocus:
    """What the package should emphasize. Eligibility was already decided by AWS-4.

    A practice intervention is built around hands-on skill. A training intervention for a
    validated knowledge gap emphasizes knowledge; for any other validated cause the package
    builds both, because every AWS-5 package carries a knowledge check and scripted practice.
    """
    if intervention_type == "practice_simulation":
        return TrainingFocus.SKILL
    if cause_domain == CauseDomain.KNOWLEDGE_GAP:
        return TrainingFocus.KNOWLEDGE
    return TrainingFocus.KNOWLEDGE_AND_SKILL


class ValidatedTrainingIntervention(FrozenModel):
    run_id: DesignId
    diagnosis_id: DesignId
    signal_id: DesignId
    # Confirmed performance gap, copied from the human-approved diagnosis.
    confirmed_gap: DesignText
    cause_domain: CauseDomain
    cause_explanation: DesignText
    performance_dimension: PerformanceDimension
    human_revised: bool
    # The AWS-4 intervention and its solution review, verbatim from the handoff.
    intervention_type: Literal["training", "practice_simulation"]
    intervention_id: DesignId
    solution_validation_id: DesignId
    solution_alignment: Literal["aligned"]
    training_design_gate: Literal["permitted"]
    recommendation: DesignText
    target_change: DesignText
    rationale: DesignText
    training_focus: TrainingFocus
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    # Operational facts the design may rely on (procedures, escalation paths, system steps).
    # Empty means none were supplied, and the designer must surface every such need instead.
    operational_context: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)
    validation_source: ValidationSource = AWS4_VALIDATION_SOURCE


def training_intervention_from_decision(context: DesignInput, decision: InterventionDecision,
                                        *, operational_context: tuple[str, ...] = ()
                                        ) -> ValidatedTrainingIntervention:
    """Consume the AWS-4 handoff decision, or refuse with a fixed reason and no provider call."""
    if decision.run_id != context.run_id or decision.diagnosis_id != context.approved.hypothesis_id:
        raise TrainingDesignRefused("intervention_mismatch")
    if decision.decision_type == DecisionType.INVESTIGATE:
        raise TrainingDesignRefused("investigation_required")
    if decision.decision_type != DecisionType.TRAINING or (
            decision.intervention_type is not None and
            decision.intervention_type not in TRAINING_INTERVENTION_TYPES):
        raise TrainingDesignRefused("not_training_intervention")
    if (decision.intervention_type is None or decision.intervention_id is None or
            decision.solution_validation_id is None or decision.training_design_gate is None or
            decision.recommendation is None or decision.target_change is None):
        # A decision without the handoff fields did not come from AWS-4 (for example the
        # controlled M5 fixture). It is never designable by a provider.
        raise TrainingDesignRefused("solution_validation_required")
    if not training_design_permitted(decision):
        raise TrainingDesignRefused("training_design_not_permitted")
    diagnosis = context.approved.diagnosis
    return ValidatedTrainingIntervention(
        run_id=context.run_id, diagnosis_id=context.approved.hypothesis_id,
        signal_id=context.approved.signal_id,
        confirmed_gap=diagnosis.observed_behavioral_defect, cause_domain=diagnosis.cause_domain,
        cause_explanation=diagnosis.explanation, performance_dimension=diagnosis.performance_dimension,
        human_revised=context.approved.human_revised,
        intervention_type=decision.intervention_type, intervention_id=decision.intervention_id,
        solution_validation_id=decision.solution_validation_id,
        solution_alignment=decision.solution_alignment, training_design_gate=decision.training_design_gate,
        recommendation=decision.recommendation, target_change=decision.target_change,
        rationale=decision.rationale,
        training_focus=training_focus_for(decision.intervention_type, diagnosis.cause_domain),
        evidence_refs=decision.evidence_refs, operational_context=tuple(operational_context),
        validation_source=AWS4_VALIDATION_SOURCE)
