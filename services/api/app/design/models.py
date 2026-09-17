"""M5 proposed intervention and training artifacts. No learner results live here."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.diagnostics.models import (ApprovedDiagnosis, EvidenceReference, FrozenModel,
                                    MAX_ID_LENGTH, MAX_TEXT_LENGTH)

DesignId = Annotated[str, Field(min_length=1, max_length=MAX_ID_LENGTH)]
DesignText = Annotated[str, Field(min_length=1, max_length=MAX_TEXT_LENGTH)]


class DecisionType(StrEnum):
    TRAINING = "training"
    NON_TRAINING = "non_training"
    INVESTIGATE = "investigate"


class DesignInput(FrozenModel):
    run_id: DesignId
    approved: ApprovedDiagnosis
    signal_criterion: str
    signal_fail_count: int
    signal_evaluated_results: int
    # The existing M3 gate validated these citations. No raw comments or source rows cross.
    allowed_evidence: tuple[EvidenceReference, ...]
    revision_rationale: str | None = None


class NextAction(FrozenModel):
    action_id: DesignId
    title: DesignText
    instructions: DesignText


class InterventionDecision(FrozenModel):
    run_id: DesignId
    diagnosis_id: DesignId
    decision_type: DecisionType
    rationale: DesignText
    evidence_refs: tuple[EvidenceReference, ...] = Field(min_length=1)
    risks: tuple[DesignText, ...] = ()
    unresolved_questions: tuple[DesignText, ...] = ()
    next_actions: tuple[NextAction, ...] = Field(min_length=1)


class TargetBehavior(FrozenModel):
    behavior_id: DesignId
    diagnosis_id: DesignId
    description: DesignText


class Objective(FrozenModel):
    objective_id: DesignId
    behavior_ids: tuple[DesignId, ...] = Field(min_length=1)
    measurable_outcome: DesignText


class Activity(FrozenModel):
    activity_id: DesignId
    activity_type: DesignText
    purpose: DesignText
    instructions: DesignText
    objective_ids: tuple[DesignId, ...] = Field(min_length=1)
    expected_learner_behavior: DesignText
    success_indicator: DesignText
    duration_minutes: int = Field(gt=0, le=240)


class OutlineSection(FrozenModel):
    section_id: DesignId
    title: DesignText
    purpose: DesignText
    duration_minutes: int = Field(gt=0, le=240)
    objective_ids: tuple[DesignId, ...] = Field(min_length=1)
    activity_ids: tuple[DesignId, ...] = ()


class CheckOption(FrozenModel):
    option_id: DesignId
    response: DesignText
    feedback: DesignText
    correct: bool


class DecisionCheck(FrozenModel):
    check_id: DesignId
    objective_ids: tuple[DesignId, ...] = Field(min_length=1)
    situation: DesignText
    question: DesignText
    options: tuple[CheckOption, ...] = Field(min_length=4, max_length=4)


class Persona(FrozenModel):
    persona_id: DesignId
    name: DesignText
    context: DesignText
    communication_style: DesignText
    emotional_state: DesignText
    knows: DesignText
    wants: DesignText
    withholding: DesignText
    success_response: DesignText
    failure_response: DesignText


class ConversationBeat(FrozenModel):
    beat_id: DesignId
    trigger: DesignText
    likely_response: DesignText
    success_branch: DesignText
    challenge_branch: DesignText


class RubricCriterion(FrozenModel):
    criterion_id: DesignId
    behavior_id: DesignId
    objective_id: DesignId
    practice_behavior: DesignText
    observable_success: DesignText
    scoring_guidance: DesignText


class PracticeScenario(FrozenModel):
    scenario_id: DesignId
    title: DesignText
    call_driver: DesignText
    learner_role: DesignText
    persona: Persona
    learner_objective: DesignText
    opening_line: DesignText
    behavior_ids: tuple[DesignId, ...] = Field(min_length=1)
    objective_ids: tuple[DesignId, ...] = Field(min_length=1)
    activity_id: DesignId
    beats: tuple[ConversationBeat, ...] = Field(min_length=1)
    completion_criteria: tuple[DesignText, ...] = Field(min_length=1)
    rubric: tuple[RubricCriterion, ...] = Field(min_length=1)
    debrief_prompts: tuple[DesignText, ...] = Field(min_length=1)


class TrainingDesign(FrozenModel):
    run_id: DesignId
    diagnosis_id: DesignId
    performance_context: DesignText
    target_behaviors: tuple[TargetBehavior, ...] = Field(min_length=1)
    objectives: tuple[Objective, ...] = Field(min_length=1)
    outline: tuple[OutlineSection, ...] = Field(min_length=1)
    activities: tuple[Activity, ...] = Field(min_length=1)
    decision_checks: tuple[DecisionCheck, ...] = ()
    practice_scenarios: tuple[PracticeScenario, ...] = Field(min_length=1)


class DesignResult(FrozenModel):
    run_id: str
    diagnosis_id: str
    created_at: datetime
    generation_mode: Literal["provider", "controlled_fixture"]
    status: Literal["ready_for_alignment_review", "alternative_recommended", "evidence_required"]
    approved_diagnosis: ApprovedDiagnosis
    intervention: InterventionDecision
    training_design: TrainingDesign | None

    @model_validator(mode="after")
    def consistent_branch(self):
        expected = {DecisionType.TRAINING: "ready_for_alignment_review",
                    DecisionType.NON_TRAINING: "alternative_recommended",
                    DecisionType.INVESTIGATE: "evidence_required"}[self.intervention.decision_type]
        if self.status != expected or (self.training_design is None) != (self.intervention.decision_type != DecisionType.TRAINING):
            raise ValueError("Intervention and result branch disagree")
        return self
