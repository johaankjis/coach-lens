"""The narrow input boundary between intervention validation (AWS-4) and training design (AWS-5).

`ValidatedTrainingIntervention` is the only thing the Training Designer designs from. Today
it is adapted from the existing M5 `InterventionDecision` plus the approved diagnosis. When
AWS-4's Intervention Reasoner and Solution Validator land, they construct it directly with
`validation_source="aws4_solution_validator"`; nothing in the designer changes.

The adapter is deliberately conservative. A training design needs a confirmed knowledge or
skill root cause, so an intervention whose approved cause is `process_gap` or `undetermined`
is refused here rather than designed around. That is a boundary rule for this designer, not
a change to the M5 orchestration, whose controlled fixture keeps its existing behavior.
"""

from typing import Literal

from pydantic import Field, model_validator

from app.diagnostics.models import CauseDomain, EvidenceReference, FrozenModel, PerformanceDimension

from .models import (DecisionType, DesignId, DesignInput, DesignText, InterventionDecision,
                     MAX_ITEMS, TrainingFocus)
from .service import TrainingDesignRefused


ValidationSource = Literal["m5_intervention_decision", "aws4_solution_validator"]

# Provisional mapping from a confirmed cause to what training must build. AWS-4 may supply an
# explicit focus instead; the mapping exists only so the current M5 decision can be adapted.
FOCUS_BY_CAUSE = {CauseDomain.KNOWLEDGE_GAP: TrainingFocus.KNOWLEDGE,
                  CauseDomain.SKILL_GAP: TrainingFocus.SKILL}


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
    # The intervention itself.
    training_focus: TrainingFocus
    intervention_summary: DesignText
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=MAX_ITEMS)
    # Operational facts the design may rely on (procedures, escalation paths, system steps).
    # Empty means none were supplied, and the designer must surface every such need instead.
    operational_context: tuple[DesignText, ...] = Field(default=(), max_length=MAX_ITEMS)
    validation_source: ValidationSource

    @model_validator(mode="after")
    def confirmed_training_cause(self):
        if self.cause_domain not in FOCUS_BY_CAUSE:
            raise ValueError("A training intervention needs a confirmed knowledge or skill root cause")
        return self


def training_intervention_from_decision(context: DesignInput, decision: InterventionDecision,
                                        *, operational_context: tuple[str, ...] = ()
                                        ) -> ValidatedTrainingIntervention:
    """Adapt the current M5 decision into the designer's input, or refuse with a fixed reason.

    Refusal reasons are fixed identifiers; their messages come from `service.REFUSAL_MESSAGES`,
    so nothing typed by a provider or reviewer reaches a client through a refusal.
    """
    if decision.run_id != context.run_id or decision.diagnosis_id != context.approved.hypothesis_id:
        raise TrainingDesignRefused("intervention_mismatch")
    if decision.decision_type == DecisionType.INVESTIGATE:
        raise TrainingDesignRefused("investigation_required")
    if decision.decision_type != DecisionType.TRAINING:
        raise TrainingDesignRefused("not_training_intervention")
    diagnosis = context.approved.diagnosis
    if diagnosis.cause_domain == CauseDomain.UNDETERMINED:
        raise TrainingDesignRefused("root_cause_unconfirmed")
    if diagnosis.cause_domain == CauseDomain.PROCESS_GAP:
        raise TrainingDesignRefused("process_gap_not_training")
    return ValidatedTrainingIntervention(
        run_id=context.run_id, diagnosis_id=context.approved.hypothesis_id,
        signal_id=context.approved.signal_id,
        confirmed_gap=diagnosis.observed_behavioral_defect, cause_domain=diagnosis.cause_domain,
        cause_explanation=diagnosis.explanation, performance_dimension=diagnosis.performance_dimension,
        human_revised=context.approved.human_revised,
        training_focus=FOCUS_BY_CAUSE[diagnosis.cause_domain],
        intervention_summary=decision.rationale, evidence_refs=decision.evidence_refs,
        operational_context=tuple(operational_context),
        validation_source="m5_intervention_decision")
